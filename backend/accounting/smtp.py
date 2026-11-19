"""Django SMTP backend with explicit visibility of partial recipient rejection."""

import email.policy

from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class EmailBackend(DjangoSMTPBackend):
    refused_recipients = None

    def _send(self, message):
        # Django's backend intentionally ignores sendmail()'s partial-rejection
        # dictionary. The application must expose that case, not call it delivered.
        sender = self.prep_address(message.from_email)
        recipients = [self.prep_address(a) for a in message.recipients()]
        if not recipients:
            return False
        payload = message.message(policy=email.policy.SMTP).as_bytes()
        self.refused_recipients = self.connection.sendmail(sender, recipients, payload)
        return True
