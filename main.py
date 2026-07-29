import os
import sys
import threading

from dotenv import load_dotenv
from imap_tools import MailBox
from tqdm import tqdm

from mail_transfer.core import EmailInfo, copy_all_folders
from mail_transfer.progress import ProgressReporter

load_dotenv()


def get_thread_count():
    return int(os.environ.get("THREADS", 1))


class TqdmProgressReporter(ProgressReporter):
    def __init__(self):
        self._position_lock = threading.Lock()
        self._thread_positions = {}
        self._bars_lock = threading.Lock()
        self._folder_bars = {}
        self._overall_bar = None

    def _get_thread_position(self):
        tid = threading.get_ident()
        with self._position_lock:
            if tid not in self._thread_positions:
                self._thread_positions[tid] = len(self._thread_positions) + 1
            return self._thread_positions[tid]

    def start_job(self, total_folders, folder_names):
        self._overall_bar = tqdm(total=total_folders, desc="Folders", unit="folder", position=0)

    def start_folder(self, folder_name, total_messages):
        position = self._get_thread_position()
        bar = tqdm(total=total_messages, desc=folder_name, unit="msg", leave=False, position=position)
        with self._bars_lock:
            self._folder_bars[folder_name] = bar

    def advance_message(self, folder_name, done, total):
        with self._bars_lock:
            bar = self._folder_bars.get(folder_name)
        if bar:
            bar.update(1)

    def finish_folder(self, folder_name):
        with self._bars_lock:
            bar = self._folder_bars.pop(folder_name, None)
        if bar:
            bar.close()
        if self._overall_bar:
            self._overall_bar.update(1)

    def finish_job(self):
        if self._overall_bar:
            self._overall_bar.close()

    def error(self, folder_name, message):
        tqdm.write(f"Error in folder {folder_name}: {message}")


def get_email_args(target):
    src_host = input(f"Enter {target} IMAP host: ")
    src_email = input(f"Enter {target} email: ")
    src_password = input(f"Enter {target} password: ")
    src_info = EmailInfo(src_host, src_email, src_password)
    return src_info

def get_email_env(prefix):
    return EmailInfo(
        os.environ[f"{prefix}_IMAP_HOST"],
        os.environ[f"{prefix}_EMAIL"],
        os.environ[f"{prefix}_PASSWORD"],
    )

def main():
    use_env = "--use_env" in sys.argv[1:]

    if use_env:
        src_info = get_email_env("SOURCE")
        dst_info = get_email_env("DEST")
    else:
        src_info = get_email_args("source")
        dst_info = get_email_args("destination")

    threads = get_thread_count()

    copy_inbox = "";
    while copy_inbox != "y" and copy_inbox != "n":
        copy_inbox = input("Do you want to copy your inbox/All Mail? (y/n): ").lower()

    reporter = TqdmProgressReporter()

    with MailBox(src_info.imap_host).login(src_info.email, src_info.password) as source, \
         MailBox(dst_info.imap_host).login(dst_info.email, dst_info.password) as dest:
         copy_all_folders(source, src_info, dst_info, dest, copy_inbox, threads, reporter=reporter)


if __name__ == "__main__":
    main()
