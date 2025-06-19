# This file is an adapter to gather reports in csv files from email attachments. 
# Each morning a report is sent to the user, and this adapter processes that report.
import imaplib
from dotenv import load_dotenv
import os

load_dotenv()

class AccuLynxEmailAdapter:
    def __init__(self):
        self.email_user = os.getenv('email-username')
        self.email_password = os.getenv('email-password')
        self.imap_server = "imap-mail.outlook.com"  # Replace with actual IMAP server
        self.mail = None
        
    def connect(self):
        """Connect to the email server."""
        self.mail = imaplib.IMAP4_SSL(self.imap_server)
        self.mail.login(self.email_user, self.email_password)
        self.mail.select("inbox")

    def fetch_reports(self):
        """Fetch reports from email attachments."""
        return