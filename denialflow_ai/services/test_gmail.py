import base64
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_FILE = "../gcp/token.json"


def enviar_email():
    # carrega credenciais salvas
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # cria serviço Gmail API
    service = build("gmail", "v1", credentials=creds)

    # conteúdo do email
    msg = MIMEText("🚀 Email de teste enviado via Gmail API com Python!")
    msg["to"] = "testescursor46@gmail.com"   # <-- troque aqui
    msg["subject"] = "Teste Gmail API"
    msg["from"] = "me"

    # codifica mensagem
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    body = {"raw": raw_message}

    # envia email
    sent = service.users().messages().send(userId="me", body=body).execute()

    print("✅ Email enviado!")
    print("📨 Message ID:", sent["id"])


if __name__ == "__main__":
    enviar_email()