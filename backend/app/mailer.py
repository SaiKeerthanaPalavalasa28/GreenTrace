"""Outgoing email over SMTP. Raises MailError when a message cannot be handed to the server, so
callers never report an email as sent when it was not."""

import html as htmllib
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


class MailError(Exception):
    pass


def mail_configured() -> bool:
    s = get_settings()
    return s.mail_console_only or bool(s.smtp_host and (s.smtp_from or s.smtp_user))


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    if s.mail_console_only:
        log.warning("MAIL (console only, not sent)\nTo: %s\nSubject: %s\n\n%s", to, subject, text)
        return
    if not mail_configured():
        raise MailError("Email delivery is not configured on the server (set SMTP_HOST, SMTP_USER, SMTP_PASSWORD).")
    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        ctx = ssl.create_default_context()
        if s.smtp_use_ssl:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        with server:
            if not s.smtp_use_ssl:
                server.starttls(context=ctx)
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password or "")
            refused = server.send_message(msg)
            if refused:
                raise MailError(f"The mail server refused the address {to}.")
    except MailError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        log.exception("sending mail to %s failed", to)
        raise MailError(f"Could not send email to {to}: {exc}") from exc


def credentials_email(*, to: str, org_name: str, role: str, password: str) -> tuple[str, str, str]:
    """(subject, text, html) for a login-credentials message. Contains only this person's login."""
    s = get_settings()
    subject = f"Your GreenTrace {role} login for {org_name}"
    access = {
        "admin": "You can view and edit everything: upload documents, change emission budgets and manage the team.",
        "manager": "You have view-only access to the dashboard, scope tabs and reports.",
        "auditor": "You have view-only access to the dashboard, scope tabs and reports, to audit flagged documents.",
    }.get(role, "")
    text = (
        f"Hello,\n\n{org_name} has been registered on GreenTrace and you were named as its {role}.\n"
        f"{access}\n\n"
        f"Sign in at: {s.app_url}/login\n"
        f"Email:    {to}\n"
        f"Password: {password}\n\n"
        "Please change this password after your first sign-in (Team page).\n"
        "If you were not expecting this email, you can ignore it.\n\n- GreenTrace"
    )
    org = htmllib.escape(org_name)
    html = f"""<div style="font-family:Arial,sans-serif;color:#14301f;max-width:520px">
<h2 style="color:#1f7549;margin:0 0 8px">GreenTrace</h2>
<p><b>{org}</b> has been registered and you were named as its <b>{role}</b>.<br>{access}</p>
<table style="background:#eef7f1;border-radius:8px;padding:12px 16px;margin:12px 0">
<tr><td style="color:#555;padding-right:12px">Email</td><td><b>{to}</b></td></tr>
<tr><td style="color:#555;padding-right:12px">Password</td><td><b style="font-family:monospace;font-size:16px">{password}</b></td></tr></table>
<p><a href="{s.app_url}/login" style="background:#1f7549;color:#fff;padding:10px 18px;border-radius:999px;text-decoration:none">Sign in</a></p>
<p style="color:#666;font-size:13px">Please change this password after your first sign-in. If you were not expecting this email, ignore it.</p></div>"""
    return subject, text, html
