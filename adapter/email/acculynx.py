# This file is an adapter to gather reports in csv files from email attachments. 
# Each morning a report is sent to the user, and this adapter processes that report.
import imaplib

class AccuLynxEmailAdapter:
    def __init__(self, email_user, email_password):
        self.email_user = email_user
        self.email_password = email_password
        self.imap_server = "imap-mail.outlook.com"  # Replace with actual IMAP server
        self.mail = None
        
    def connect(self):
        """Connect to the email server."""
        self.mail = imaplib.IMAP4_SSL(self.imap_server)
        self.mail.login(self.email_user, self.email_password)
        self.mail.select("inbox")

    def fetch_reports(self):
        """Fetch reports from email attachments."""
        result, data = self.mail.search(None, "ALL")
        email_ids = data[0].split()
        reports = []

        for email_id in email_ids:
            result, msg_data = self.mail.fetch(email_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            for part in msg.walk():
                if part.get_content_type() == "application/vnd.ms-excel":
                    reports.append(part.get_payload(decode=True))

        return reports