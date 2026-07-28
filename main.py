import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from imap_tools import MailBox, FolderInfo
from tqdm import tqdm

load_dotenv()

_position_lock = threading.Lock()
_thread_positions = {}


def get_thread_position():
    tid = threading.get_ident()
    with _position_lock:
        if tid not in _thread_positions:
            _thread_positions[tid] = len(_thread_positions) + 1
        return _thread_positions[tid]


def get_thread_count():
    return int(os.environ.get("THREADS", 1))


class EmailInfo:
    def __init__(self, imap_host, email, password):
        self.imap_host = imap_host
        self.email = email
        self.password = password


def fetch_messages(mailbox: MailBox):
    pass

def copy_message(message, folder: str, dest: MailBox):
    dest.append(message, folder, dt=message.date, flag_set=message.flags)

def copy_folder(source: MailBox, src_info: EmailInfo, folder: FolderInfo, dest: MailBox):
    source.folder.set(folder.name)

    dest_folder = f"{src_info.email}/{folder.name}"
    if not dest.folder.exists(dest_folder):
        dest.folder.create(dest_folder)

    total = source.folder.status(folder.name, ["MESSAGES"])["MESSAGES"]
    position = get_thread_position()
    for m in tqdm(source.fetch(bulk=100), total=total, desc=folder.name, unit="msg", leave=False, position=position):
        copy_message(m, dest_folder, dest)


def copy_folder_worker(src_info: EmailInfo, dst_info: EmailInfo, folder: FolderInfo):
    with MailBox(src_info.imap_host).login(src_info.email, src_info.password) as source, \
         MailBox(dst_info.imap_host).login(dst_info.email, dst_info.password) as dest:
        copy_folder(source, src_info, folder, dest)


def copy_all_folders(source: MailBox, src_info: EmailInfo, dst_info: EmailInfo, dest: MailBox, copy_inbox: str, threads: int):
    # Create folder where all copied folders will be put
    if not dest.folder.exists(src_info.email):
        dest.folder.create(src_info.email)

    folders = [f for f in source.folder.list() if "\\Noselect" not in f.flags]
    folders_to_copy = []
    for f in folders:
        if "\\Junk" in f.flags:
            continue
        if (copy_inbox == "n" and (f.name == "INBOX" or "\\All" in f.flags)):
            continue
        folders_to_copy.append(f)

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(copy_folder_worker, src_info, dst_info, f) for f in folders_to_copy]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Folders", unit="folder", position=0):
            future.result()

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

    with MailBox(src_info.imap_host).login(src_info.email, src_info.password) as source, \
         MailBox(dst_info.imap_host).login(dst_info.email, dst_info.password) as dest:
         copy_all_folders(source, src_info, dst_info, dest, copy_inbox, threads)
        

if __name__ == "__main__":
    main()
