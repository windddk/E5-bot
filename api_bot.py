import os
from O365 import Account


def check_mailbox(account):
    print("check mail box")
    mailbox = account.mailbox()
    inbox = mailbox.inbox_folder()
    for message in inbox.get_messages():
        print(message)
    print("check mail box done")


def send_notify_email(account, content):
    print("begin send email...")
    m = account.new_message()
    m.to.add(os.environ["NOTIFY_EMAIL"])
    m.subject = 'Testing E5-bot'
    m.body = "This is a test email from github workflow, check it please" + "\r\n" + content
    m.send()
    print("send email done...")


def check_onedrive(account):
    print("check onedrive")
    storage = account.storage()
    my_drive = storage.get_default_drive()  # or get_drive('drive-id')
    root_folder = my_drive.get_root_folder()
    onedrive_contents = ""
    for item in root_folder.get_items(limit=25):
        onedrive_contents += str(item) + "\r\n"
    print("check onedrive done")
    return onedrive_contents


if __name__ == "__main__":
    client_id = os.environ['CONFIG_ID']
    secret = os.environ['CONFIG_SECRET']
    credentials = (client_id, secret)

    scopes = ['basic', 'message_all', 'onedrive_all']
    account = Account(credentials, scopes=scopes)
    if not account.is_authenticated:
        account.authenticate()

    check_mailbox(account)
    content = check_onedrive(account)
    send_notify_email(account, content)

