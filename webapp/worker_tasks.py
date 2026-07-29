from imap_tools import MailBox
from rq import get_current_job

from mail_transfer.core import EmailInfo, copy_all_folders
from mail_transfer.progress import NULL_REPORTER
from webapp.config import settings
from webapp.progress import RQProgressReporter
from webapp.security import decrypt_payload, scrub_secrets, validate_public_host


def run_migration(encrypted_payload: bytes) -> dict:
    job = get_current_job()
    payload = decrypt_payload(encrypted_payload)

    src = EmailInfo(**payload["source"])
    dst = EmailInfo(**payload["dest"])
    secret_values = [src.password, dst.password]

    reporter = RQProgressReporter(job, secret_values) if job is not None else NULL_REPORTER
    threads = min(payload["threads"], settings.max_threads)
    copy_inbox = payload["copy_inbox"]

    try:
        # Re-validate immediately before connecting: this is the authoritative
        # SSRF check (the web layer already checked once for fast feedback).
        validate_public_host(src.imap_host)
        validate_public_host(dst.imap_host)

        with MailBox(src.imap_host).login(src.email, src.password) as source, \
             MailBox(dst.imap_host).login(dst.email, dst.password) as dest:
            copy_all_folders(source, src, dst, dest, copy_inbox, threads, reporter=reporter)

        reporter.finish_job()
        return {"status": "done"}
    except Exception as e:
        raw_message = str(e)
        reporter.error(None, raw_message)
        scrubbed = scrub_secrets(raw_message, secret_values)
        # `from None`: do not chain the original exception, or RQ's stored
        # traceback would still contain the unscrubbed credential values.
        raise RuntimeError(scrubbed) from None
