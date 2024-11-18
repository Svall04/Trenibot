from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
import json
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackContext,
    ConversationHandler,
    MessageHandler,
    filters,
)
import csv
import os
from datetime import datetime


TOKEN = "7430502472:AAFiI3PmuZRzXxeWopXF82G4JobAMLLADYo"
scheduler = AsyncIOScheduler()

# Configura il logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Stati per la conversazione
IMPOSTA_TRENO, IMPOSTA_ORA = range(2)

# Funzione per inviare i ritardi giornalieri
async def invia_ritardi_giornalieri(bot, chat_id, numero_treno):
    try:
        info = n_info(numero_treno)
        informazioni_treno = retrive(info, 0)
        messaggio = (
            f"Il treno {numero_treno} in arrivo da {informazioni_treno[0]} "
            f"con arrivo programmato a {informazioni_treno[1]} alle {informazioni_treno[2]} "
            f"è in ritardo di {informazioni_treno[3]} minuti.\n"
        )
        await bot.send_message(chat_id=chat_id, text=messaggio)
    except Exception as e:
        logger.error(f"Errore nell'invio del ritardo per il treno {numero_treno}: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"Errore nel recupero del ritardo per il treno {numero_treno}."
        )


# Funzione per gestire il comando /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "Ciao! Usa il comando /nuovo per scegliere il treno e l'orario a cui vuoi ricevere informazioni sul ritardo! \nHai anche a disposizione il comando /reminder per visualizzare i reminder giornlieri e il comando /elimina per eliminare un reminder."
    )

# Funzione per impostare il numero del treno e l'orario
async def nuovo(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Inserisci il numero del treno che vuoi monitorare.")
    return IMPOSTA_TRENO

# Funzione per salvare il numero del treno
async def imposta_treno(update: Update, context: CallbackContext) -> int:
    try:
        numero_treno = int(update.message.text)
        context.user_data['numero_treno'] = numero_treno
        await update.message.reply_text(
            "Ora inserisci l'orario (es. 09:30) a cui vuoi ricevere le notifiche."
        )
        return IMPOSTA_ORA
    except ValueError:
        await update.message.reply_text(
            "Per favore, inserisci un numero di treno valido.")
        return IMPOSTA_TRENO

# Funzione per salvare l'orario e pianificare il promemoria giornaliero

async def imposta_ora(update: Update, context: CallbackContext) -> int:
    ora = update.message.text
    try:
        ora_split = ora.split(":")
        if len(ora_split) != 2 or not ora_split[0].isdigit(
        ) or not ora_split[1].isdigit():
            raise ValueError

        context.user_data['ora'] = ora
        chat_id = update.message.chat_id
        numero_treno = context.user_data['numero_treno']

        # Crea un identificativo unico per il job
        job_id = f"{chat_id}_{numero_treno}_{ora}"

        # Imposta lo scheduler per inviare il messaggio ogni giorno all'orario specificato
        trigger = CronTrigger(
            hour=int(ora_split[0]),
            minute=int(ora_split[1]),
            timezone="Europe/Rome"  # Specifica il fuso orario corretto
        )
        scheduler.add_job(
            invia_ritardi_giornalieri,
            trigger,
            args=[context.bot, chat_id, numero_treno],
            id=job_id,
            replace_existing=True  # Sostituisce un job con lo stesso ID
        )

        # Salva i dati in un file CSV
        salva_reminder(chat_id, numero_treno, ora)

        await update.message.reply_text(
            f"Riceverai aggiornamenti sul ritardo del treno {numero_treno} ogni giorno alle {ora}."
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "Per favore, inserisci un orario valido nel formato HH:MM.")
        return IMPOSTA_ORA


def ripristina_reminder(application):
    file = "data.csv"
    if os.path.exists(file):
        with open(file, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                chat_id = int(row[0])
                numero_treno = row[1]
                ora = row[2]
                ora_split = ora.split(":")
                
                # Definisci il trigger per il job
                trigger = CronTrigger(
                    hour=int(ora_split[0]),
                    minute=int(ora_split[1]),
                    timezone="Europe/Rome"  # Specifica il fuso orario corretto
                )
                
                # Crea un job nello scheduler
                scheduler.add_job(
                    invia_ritardi_giornalieri,
                    trigger,
                    args=[application.bot, chat_id, numero_treno],
                    id=f"{chat_id}_{numero_treno}_{ora}",  # Un identificativo univoco
                    replace_existing=True
                )
                logger.info(f"Ripristinato reminder per treno {numero_treno} alle {ora} per chat {chat_id}")



# Funzione per visualizzare i reminder attivi
async def visualizza_reminder(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    reminders = leggi_reminder(chat_id)

    if reminders:
        messaggio = "Ecco i tuoi reminder attivi:\n"
        for idx, (numero_treno, ora) in enumerate(reminders):
            messaggio += f"{idx + 1}. Treno {numero_treno} alle {ora}\n"
        await update.message.reply_text(messaggio)
    else:
        await update.message.reply_text("Non hai reminder attivi.")

# Funzione per eliminare un reminder
async def elimina(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    reminders = leggi_reminder(chat_id)

    if not reminders:
        await update.message.reply_text("Non hai reminder da eliminare.")
        return

    await update.message.reply_text(
        "Inserisci il numero del reminder che vuoi eliminare.")
    context.user_data[
        'reminders'] = reminders  # Salva i reminder per riferimento
    return 1  # Attendi l'input dell'utente

async def conferma_elimina_reminder(update: Update,
                                    context: CallbackContext) -> int:
    try:
        indice = int(update.message.text) - 1
        reminders = context.user_data.get('reminders')

        if 0 <= indice < len(reminders):
            chat_id = update.message.chat_id
            reminders.pop(indice)
            salva_tutti_reminder(chat_id,
                                 reminders)  # Riscrivi i reminder nel CSV
            await update.message.reply_text("Reminder eliminato con successo.")
            return ConversationHandler.END
        else:
            await update.message.reply_text("Indice non valido. Riprova.")
            return 1
    except ValueError:
        await update.message.reply_text(
            "Per favore, inserisci un numero valido.")
        return 1

# Funzione per gestire il comando /info
async def info_treno(update: Update, context: CallbackContext) -> None:
    try:
        # Verifica che sia stato fornito un numero di treno
        if len(context.args) != 1 or not context.args[0].isdigit():
            await update.message.reply_text(
                "Per favore, usa il comando nel formato /info <numero_treno>.")
            return

        # Recupera il numero del treno
        numero_treno = int(context.args[0])
        
        # Ottieni le informazioni sul treno
        info = n_info(numero_treno)
        
        # Verifica se le informazioni sono disponibili
        if not info:
            await update.message.reply_text("Treno non trovato.")
            return

        # Ottieni le informazioni dettagliate del treno
        informazioni_treno = retrive(info, 0)

        # Costruisci il messaggio di risposta con le informazioni
        messaggio = (
            f"Informazioni per il treno {numero_treno}:\n"
            f"Origine: {informazioni_treno[0]}\n"
            f"Destinazione: {informazioni_treno[1]}\n"
            f"Orario di arrivo previsto: {informazioni_treno[2]}\n"
            f"Ritardo: {informazioni_treno[3]} minuti\n"
            f"Posizione ultimo rilevamento: {informazioni_treno[4]}\n"
            f"Ultimo rilevamento: {informazioni_treno[5]}"
        )

        await update.message.reply_text(messaggio)

    except Exception as e:
        logger.error(f"Errore nel recupero delle informazioni per il treno {numero_treno}: {e}")
        await update.message.reply_text(
            "Si è verificato un errore durante il recupero delle informazioni. Riprova più tardi."
        )

# Funzione per salvare un reminder su CSV
def salva_reminder(chat_id, numero_treno, ora):
    file = "data.csv"
    with open(file, "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([chat_id, numero_treno, ora])

# Funzione per leggere i reminder da CSV
def leggi_reminder(chat_id):
    file = "data.csv"
    reminders = []
    if os.path.exists(file):
        with open(file, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if int(row[0]) == chat_id:
                    reminders.append((row[1], row[2]))  # Restituisci solo numero_treno e ora
    return reminders

# Funzione per riscrivere i reminder dopo un'eliminazione
def salva_tutti_reminder(chat_id, reminders):
    file = "data.csv"
    rows = []
    # Leggi tutte le righe che non appartengono a questo chat_id
    if os.path.exists(file):
        with open(file, "r") as f:
            reader = csv.reader(f)
            rows = [row for row in reader if int(row[0]) != chat_id]
    # Aggiungi i reminder aggiornati per questo chat_id
    for numero_treno, ora in reminders:
        rows.append([chat_id, numero_treno, ora])  # Mantieni il chat_id
    # Riscrivi il file
    with open(file, "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerows(rows)

# Funzioni per recuperare le informazioni dei treni
def n_info(N_train):
    '''Restituisce una lista di informazioni sui treni, come destinazione e ritardo.'''
    url = 'http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/cercaNumeroTrenoTrenoAutocomplete/' + str(
        N_train)
    response = requests.get(url)
    TRENI = []
    data = response.text.split(sep='\n')
    for i in range(len(data) - 1):
        data_i = data[i].split(sep='|')
        [n_train, station_code, time] = data_i[1].split(sep='-')
        [nome, destinazione] = data_i[0].split(sep='-')
        TRENI.append([destinazione, station_code, n_train, time])
    return TRENI

def unico_Unix_to_str(a):
    data_ora=datetime.utcfromtimestamp(a/1000)
    return(str(str(data_ora.hour))+str(':')+str(data_ora.minute))

def retrive(info,a):
    ###la funzione prende le info del treno e restituisce: origine, destinazione, orario destinazione previsto, minuti di ritardo, posizione ultimo rilevamento, ora ultimo rilevamento.###
    Id = info[a][1]
    ntrain = info[a][2]
    time = info[a][3]
    url2 = 'http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/andamentoTreno/' + str(Id) + '/' + str(ntrain) +'/' + str(time)
    response = requests.get(url2)
    if(response):
        diz = json.loads(response.text)
        return([diz['origine'],diz['destinazione'],diz['compOrarioArrivo'],diz['ritardo'],diz['stazioneUltimoRilevamento'],unico_Unix_to_str(diz['oraUltimoRilevamento'])])
    else:
        return('ERRORE')
    
def retrive_ritardo(info, a):
    informazioni_treno = retrive(info, a)
    return informazioni_treno[3]  # Restituisce solo il ritardo (minuti)

def main():
    application = ApplicationBuilder().token(TOKEN).read_timeout(
        10).write_timeout(10).concurrent_updates(True).build()

    # Ripristina i reminder all'avvio
    ripristina_reminder(application)

    # Aggiungi il comando /start
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info_treno))
    application.add_handler(CommandHandler("reminder", visualizza_reminder))

    # ConversationHandler per eliminare un reminder
    elimina_handler = ConversationHandler(
        entry_points=[CommandHandler("elimina", elimina)],
        states={
            1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               conferma_elimina_reminder)
            ],
        },
        fallbacks=[],
    )
    application.add_handler(elimina_handler)

    # ConversationHandler per impostare il treno e l'ora
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("nuovo", nuovo)],
        states={
            IMPOSTA_TRENO:
            [MessageHandler(filters.TEXT & ~filters.COMMAND, imposta_treno)],
            IMPOSTA_ORA:
            [MessageHandler(filters.TEXT & ~filters.COMMAND, imposta_ora)],
        },
        fallbacks=[],
    )
    application.add_handler(conv_handler)

    # Avvia il bot
    scheduler.start()
    application.run_polling()

if __name__ == "__main__":
    main()
    