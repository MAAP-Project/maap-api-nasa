import email.encoders
import html
import logging
import re
import smtplib
import os

from api import settings
from api.models.member import Member
from api.utils.environments import Environments, get_environment
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum

log = logging.getLogger(__name__)
CHARSET = "utf-8"

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))


class EmailFormats(Enum):
    PLAIN = 'plain'
    HTML = 'html'


class Email(object):

    def __init__(self, from_, to, subject, html_message, text_message, cc=None):

        self.from_ = from_
        self.to = list(to)
        self.cc = [addr for addr in (cc or []) if addr]

        self.email = MIMEMultipart('mixed')
        self.email['From'] = from_
        self.email['To'] = ",".join(self.to)
        if self.cc:
            self.email['Cc'] = ",".join(self.cc)
        self.email['Subject'] = subject

        # Create Message Body
        message_body = MIMEMultipart('alternative')

        # Add text/plain message part
        text = MIMEText(text_message.encode(CHARSET), EmailFormats.PLAIN.value, CHARSET)
        message_body.attach(text)

        # Add text/html message part
        html = MIMEText(html_message.encode(CHARSET), EmailFormats.HTML.value, CHARSET)
        message_body.attach(html)

        # Add message body to parent container
        self.email.attach(message_body)

    def send(self):

        with smtplib.SMTP(settings.SMTP_HOSTNAME, settings.SMTP_PORT) as smtp_server:

            smtp_server.set_debuglevel(settings.SMTP_DEBUG_LEVEL)

            smtp_server.ehlo()
            smtp_server.starttls()
            smtp_server.ehlo()

            try:
                smtp_server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            except smtplib.SMTPException as e:
                log.error("Unable to login to SMTP server: ", e.strerror)
                raise e

            try:
                smtp_server.send_message(self.email, self.from_, self.to + self.cc)
            except smtplib.SMTPException as e:
                log.error("Unable to send email: ", e.strerror)
                raise e

    def __str__(self):
        return self.email.as_string()


def send_user_status_change_email(member: Member, is_new, is_active, base_url):

    environment_info = get_environment_info(base_url)

    template_key_status = "active" if is_active else "suspended"
    template_key_user = "new" if is_new else "existing"

    if is_new:
        subject = "New Registered User"
        if not is_active:
            subject += " (Action Needed)"
    else:
        subject = "User " + ("Activated" if is_active else "Deactivated")

    email_message_subj = "MAAP ({}): {}".format(environment_info['env'], subject)

    # Build HTML body
    email_message_html = ""
    template_file = SCRIPT_PATH + "/email_templates/{}_{}_user_admin_alert.html".format(template_key_user,
                                                                                        template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_html = file.read().format(
            environment_info=environment_info,
            member_email=member.email,
            member_display_name=member.get_display_name(),
            title=email_message_subj
        )

    # Build Text body
    email_message_txt = ""
    template_file = SCRIPT_PATH + "/email_templates/{}_{}_user_admin_alert.txt".format(template_key_user,
                                                                                       template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_txt = file.read().format(
            environment_info=environment_info,
            member_email=member.email,
            member_display_name=member.get_display_name(),
            title=email_message_subj
        )

    # Create and send the email
    email_message = Email(
        settings.EMAIL_NO_REPLY,
        settings.EMAIL_JPL_ADMINS.split(","),
        email_message_subj,
        email_message_html,
        email_message_txt
    )
    log.info("Sending '{} {} user' email for {} to JPL Admins ({})".format(
        template_key_user,
        template_key_status,
        member.get_display_name(),
        settings.EMAIL_JPL_ADMINS
    ))
    email_message.send()
    log.info("Email Sent!")


def send_user_status_update_active_user_email(member: Member, base_url):
    send_user_status_update_email(member, True, base_url)


def send_user_status_update_suspended_user_email(member: Member, base_url):
    send_user_status_update_email(member, False, base_url)


def send_user_status_update_email(member: Member, is_active, base_url):

    environment_info = get_environment_info(base_url)
    email_message_subj = "Your MAAP account has been {}".format("activated" if is_active else "deactivated")
    template_key_status = "active" if is_active else "suspended"

    # Build HTML body
    email_message_html = ""
    template_file = SCRIPT_PATH + "/email_templates/user_status_update_{}_user_alert.html".format(template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_html = file.read().format(
            environment_info=environment_info,
            member_first_name=member.first_name,
            support_email=settings.EMAIL_SUPPORT,
            title=email_message_subj,
        )

    # Build Text body
    email_message_txt = ""
    template_file = SCRIPT_PATH + "/email_templates/user_status_update_{}_user_alert.txt".format(template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_txt = file.read().format(
            environment_info=environment_info,
            member_first_name=member.first_name,
            support_email=settings.EMAIL_SUPPORT,
            title=email_message_subj,
        )

    # Create and send the email
    email_message = Email(
        settings.EMAIL_SUPPORT,
        [member.email],
        email_message_subj,
        email_message_html,
        email_message_txt
    )
    log.info("Sending 'User Status Update ({})' email for {} to {}".format(
        template_key_status,
        member.get_display_name(),
        member.email
    ))
    email_message.send()
    log.info("Email Sent!")


def send_welcome_to_maap_active_user_email(member: Member, base_url):
    send_welcome_to_maap_user_email(member, True, base_url)


def send_welcome_to_maap_suspended_user_email(member: Member, base_url):
    send_welcome_to_maap_user_email(member, False, base_url)


def send_welcome_to_maap_user_email(member: Member, is_active, base_url):

    environment_info = get_environment_info(base_url)
    email_message_subj = "Welcome to the Multi-Mission Algorithm and Analysis Platform (MAAP)!"
    template_key_status = "active" if is_active else "suspended"

    # Build HTML body
    email_message_html = ""
    template_file = SCRIPT_PATH + "/email_templates/welcome_to_maap_{}_user_alert.html".format(template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_html = file.read().format(
            environment_info=environment_info,
            member_first_name=member.first_name,
            support_email=settings.EMAIL_SUPPORT,
            title=email_message_subj,
        )

    # Build Text body
    email_message_txt = ""
    template_file = SCRIPT_PATH + "/email_templates/welcome_to_maap_{}_user_alert.txt".format(template_key_status)
    with open(template_file, "r", encoding=CHARSET) as file:
        email_message_txt = file.read().format(
            environment_info=environment_info,
            member_first_name=member.first_name,
            support_email=settings.EMAIL_SUPPORT,
            title=email_message_subj,
        )

    # Create and send the email
    email_message = Email(
        settings.EMAIL_SUPPORT,
        [member.email],
        email_message_subj,
        email_message_html,
        email_message_txt
    )
    log.info("Sending 'Welcome to MAAP ({} User)' email for {} to {}".format(
        template_key_status,
        member.get_display_name(),
        member.email
    ))
    email_message.send()
    log.info("Email Sent!")


def _render_template(template_name, template_vars):
    """Read an email template from email_templates/ and str.format it."""
    template_file = SCRIPT_PATH + "/email_templates/" + template_name
    with open(template_file, "r", encoding=CHARSET) as file:
        return file.read().format(**template_vars)


# ---------------------------------------------------------------------------
# Admin-triggered welcome email (Console: Admin > Users > "Preview & send
# welcome email"). The admin previews and may edit the subject and plain-text
# body; the HTML part is generated from that text so what was previewed is
# what is sent. Distinct from the registration-time welcome_to_maap_*
# notifications and NOT gated by MEMBER_EMAIL_NOTIFICATIONS_ENABLED.
# ---------------------------------------------------------------------------

WELCOME_EMAIL_SUBJECT = "Welcome to MAAP: your account has been activated"

_LINK_RE = re.compile(r'(https?://[^\s<>"]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)')
_BULLET_RE = re.compile(r'^\s*[-*\u2022]\s+')


def get_welcome_email_cc():
    """CC list for the welcome email (settings.MAAP_WELCOME_EMAIL_CC, comma-delimited)."""
    return [addr.strip() for addr in settings.MAAP_WELCOME_EMAIL_CC.split(",") if addr.strip()]


def _linkify(escaped_text):
    """Wrap bare URLs and email addresses in anchors. Input is already HTML-escaped."""
    def repl(match):
        target, trail = match.group(0), ''
        while target and target[-1] in '.,;:!?)]':
            trail, target = target[-1] + trail, target[:-1]
        href = target if target.startswith('http') else 'mailto:' + target
        return '<a href="{0}">{1}</a>{2}'.format(href, target, trail)
    return _LINK_RE.sub(repl, escaped_text)


def text_to_html(text):
    """Plain text -> simple HTML: blank-line-separated blocks become paragraphs
    (single newlines -> <br />), blocks of '- ' lines become lists, a lone
    line ending in ':' becomes a bold lead-in, and URLs/emails become links.
    Everything is HTML-escaped first."""
    blocks = re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip())
    out = []
    for block in blocks:
        lines = [line.rstrip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue
        if all(_BULLET_RE.match(line) for line in lines):
            items = ''.join('<li>{}</li>'.format(_linkify(html.escape(_BULLET_RE.sub('', line))))
                            for line in lines)
            out.append('<ul>{}</ul>'.format(items))
        elif len(lines) == 1 and lines[0].endswith(':'):
            out.append('<p><strong>{}</strong></p>'.format(_linkify(html.escape(lines[0]))))
        else:
            out.append('<p>{}</p>'.format('<br />'.join(_linkify(html.escape(line)) for line in lines)))
    return '\n    '.join(out)


def build_welcome_email_draft(member: Member, base_url):
    """The default welcome email for a member, as the admin sees it before
    sending: from/to/cc plus an editable subject and plain-text body."""
    environment_info = get_environment_info(base_url)
    body = _render_template("welcome_email_user_alert.txt", {
        'member_first_name': member.first_name or member.username,
        'hub_url': environment_info['urls']['hub'],
        'docs_url': settings.MAAP_DOCS_URL,
        'slack_invite_url': settings.MAAP_SLACK_INVITE_URL,
        'mailing_list_email': settings.MAAP_MAILING_LIST_EMAIL,
    })
    return {
        'from': settings.EMAIL_SUPPORT,
        'to': member.email,
        'cc': get_welcome_email_cc(),
        'subject': WELCOME_EMAIL_SUBJECT,
        'body': body.strip() + "\n",
    }


def send_welcome_email(member: Member, base_url, subject=None, body=None):
    """Send the welcome email to a member, CC'ing support. subject/body default
    to build_welcome_email_draft(); pass the admin's edited versions to send
    those instead. Raises on SMTP failure so the caller can report it."""
    environment_info = get_environment_info(base_url)
    draft = build_welcome_email_draft(member, base_url)
    subject = (subject or '').strip() or draft['subject']
    body = body if body and body.strip() else draft['body']

    header_plain = environment_info['template']['header']['plain']
    email_message_txt = (header_plain + "\n\n" if header_plain else "") + body
    email_message_html = _render_template("welcome_email_user_alert.html", {
        'environment_info': environment_info,
        'title': subject,
        'content': text_to_html(body),
    })

    email_message = Email(
        draft['from'],
        [member.email],
        subject,
        email_message_html,
        email_message_txt,
        cc=draft['cc'],
    )
    log.info("Sending 'Welcome' email for {} to {} (cc {})".format(
        member.get_display_name(), member.email, ", ".join(draft['cc'])))
    email_message.send()
    log.info("Email Sent!")


def get_environment_info(base_url):

    env = get_environment(base_url)

    email_header = {
        EmailFormats.PLAIN.value: '',
        EmailFormats.HTML.value: ''
    }
    if env != Environments.OLD_OPS and env != Environments.NEW_OPS:
        email_header = {
            EmailFormats.PLAIN.value: "*** THIS EMAIL WAS SENT FROM THE MAAP {} ENVIRONMENT ***".format(
                env.value['label'].upper()),
            EmailFormats.HTML.value: """
                    <div style="width:100%;padding:10px;margin-bottom:10px;text-align:center;background-color:#FFC107;color:#000000;">
                        <strong>*** THIS EMAIL WAS SENT FROM THE MAAP {} ENVIRONMENT ***</strong>
                    </div>
                """.format(env.value['label'].upper())
        }

    portal_base_url = "https://maap-project.org"
    if env != Environments.NEW_OPS:
        portal_base_url = "https://{}.maap-project.org".format(env.value['cname'].lower())

    hub_url = settings.MAAP_HUB_URL or "https://hub.maap-project.org"
    if not settings.MAAP_HUB_URL and env != Environments.NEW_OPS:
        hub_url = "https://hub.{}.maap-project.org".format(env.value['cname'].lower())

    data = {
        'env': env.value['label'].upper(),
        'template': {
            'header': email_header
        },
        'urls': {
            'logo': portal_base_url + '/wp-content/uploads/2021/10/nasamaaplogo3.png',
            'hub': hub_url,
            'portal': {
                'base_url': portal_base_url,
                'maap_admin': portal_base_url + settings.PORTAL_ADMIN_DASHBOARD_PATH,
                'open_policies': portal_base_url + "/open-policies/",
                'privacy_policy': 'https://www.nasa.gov/about/highlights/HP_Privacy.html',
                'tos': portal_base_url + "/terms-of-service/",
                'user_guides': portal_base_url + "/user-guides/",
            },
            'github': {
                'issues': 'https://github.com/MAAP-Project/ZenHub/issues'
            },
        },
    }

    return data
