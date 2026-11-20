# DS3003 project - near real time + periodic data warehouse using MESHJOIN
# run: python main.py   (options: --peak 80 --non-peak 10 --hour-seconds 60 --skip-prep)

import argparse
import getpass
import os
import sys

import config
import data_prep
import db
from control import Control, log
from meshjoin import MeshJoinThread, StreamBuffer
from sources import OnlineThread, PeriodicThread

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
DEFAULT_SCRIPT = os.path.join(PROJECT_ROOT, "Create-DW", "create_dw.sql")
DEFAULT_RAW = os.path.join(PROJECT_ROOT, "Data", "Online Retail.xlsx")
DEFAULT_ONLINE = os.path.join(PROJECT_ROOT, "Data", "online_sales_stream.csv")

HELP_TEXT = """Commands:
  online        online form only, no periodic groups are extracted
  periodic      periodic groups only, the stream reader is paused
  both          both forms, Live transactions are taken first
  peak [n]      fast stream, shedding to disk allowed (n = new speed)
  non-peak [n]  slow stream, shed transactions are processed (n = new speed)
  status        show the mode, speed, stream buffer, H and shed disk
  quit          stop the threads and close the program"""


def parse_arguments():
    parser = argparse.ArgumentParser(description="MESHJOIN retail Data Warehouse")
    parser.add_argument("--peak", type=int, default=config.PEAK_RATE,
                        help="online transactions per second in peak time")
    parser.add_argument("--non-peak", type=int, default=config.NON_PEAK_RATE,
                        help="online transactions per second in non-peak time")
    parser.add_argument("--hour-seconds", type=float, default=config.SECONDS_PER_HOUR,
                        help="real seconds that make one simulated hour")
    parser.add_argument("--start", choices=["peak", "non-peak"], default="peak",
                        help="stream arrival mode at startup")
    parser.add_argument("--raw", default=DEFAULT_RAW,
                        help="path of Online Retail.xlsx")
    parser.add_argument("--schema", default=DEFAULT_SCRIPT,
                        help="path of create_dw.sql")
    parser.add_argument("--skip-prep", action="store_true",
                        help="skip steps 1-2 and reuse the prepared data; "
                             "the DW and the shed table are emptied")
    return parser.parse_args()


def ask(prompt, default=None):
    # ask one question; an empty answer keeps the default
    label = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    answer = input(label).strip()
    return answer if answer else default


def ask_password():
    # the password is typed at run time and is never stored in the code
    if sys.stdin.isatty():
        return getpass.getpass("Password: ")
    return input("Password: ")   # input was piped, getpass needs a console


def ask_connection_details():
    print("Enter the database connection details (press Enter for the default).")
    settings = {
        "host": ask("Host", "localhost"),
        "port": int(ask("Port", "3306")),
        "database": ask("Database name", "retail_dw"),
        "user": ask("User name", "root"),
    }
    settings["password"] = ask_password()
    online_path = ask("Path of the online file", DEFAULT_ONLINE)
    return settings, online_path


def print_status(control, stream_buffer):
    live, periodic = stream_buffer.counts()
    print(f"""[STATUS]
  Form mode      : {control.form_mode}
  Arrival mode   : {control.arrival_mode()}  (speed now {control.rate()} transactions/second; peak = {control.peak_rate}, non-peak = {control.non_peak_rate})
  Stream buffer  : {live + periodic:,} of {config.STREAM_BUFFER_LIMIT:,} transactions  (Live {live:,}, Periodic {periodic:,})
  Hash table H   : {control.h_size:,} transactions in {control.queue_length} queue chunks
  Disk buffer    : customer partition {control.customer_page} of {control.customer_partitions}, product partition {control.product_page} of {control.product_partitions}
  Shed disk      : {control.shed_on_disk:,} transactions still on the shed disk
  Shed counts    : shed in peak {control.shed_in_peak:,}, shed in non-peak {control.shed_in_non_peak:,}, read back {control.shed_read_back:,}
  Online stream  : {control.online_sent:,} of {control.online_total:,} transactions sent{' (finished)' if control.online_finished else ''}
  Periodic       : simulated hour {control.hour}, groups extracted {control.groups_released} of {control.groups_total}
  DW fact_sales  : {control.loaded_live + control.loaded_periodic:,} tuples loaded  (Live {control.loaded_live:,}, Periodic {control.loaded_periodic:,}); {control.periodic_waiting:,} periodic waiting for the hourly load
  MESHJOIN       : {control.iterations:,} iterations, unmatched transactions {control.unmatched}""", flush=True)
    if control.failed:
        print(f"  ERROR          : {control.failed}", flush=True)


def set_speed(control, parts, peak):
    # handle `peak [n]` and `non-peak [n]`
    if len(parts) > 1:
        if not parts[1].isdigit() or int(parts[1]) < 1:
            print("[CMD] The speed must be a whole number above zero.")
            return
        if peak:
            control.peak_rate = int(parts[1])
        else:
            control.non_peak_rate = int(parts[1])
    control.peak = peak
    if peak:
        print(f"[CMD] Arrival mode = peak, {control.peak_rate} transactions/second. "
              f"Periodic transactions may be shed to disk.", flush=True)
    else:
        print(f"[CMD] Arrival mode = non-peak, {control.non_peak_rate} transactions/second. "
              f"Shed transactions are read back and processed.", flush=True)


def command_loop(control, stream_buffer):
    # step 5: keep accepting commands until the program is closed
    while True:
        try:
            parts = input().strip().lower().split()
        except (EOFError, KeyboardInterrupt):
            parts = ["quit"]
        if not parts:
            continue
        command = parts[0]
        if command in ("online", "periodic", "both"):
            control.form_mode = command
            notes = {"online": "online form only, periodic groups are not extracted",
                     "periodic": "periodic groups only, the stream reader is paused",
                     "both": "both forms, Live transactions first"}
            print(f"[CMD] Form mode = {command}: {notes[command]}", flush=True)
        elif command == "peak":
            set_speed(control, parts, peak=True)
        elif command in ("non-peak", "nonpeak"):
            set_speed(control, parts, peak=False)
        elif command == "status":
            print_status(control, stream_buffer)
        elif command == "help":
            print(HELP_TEXT, flush=True)
        elif command in ("quit", "exit"):
            return
        else:
            print(f"[CMD] Unknown command '{command}'. Type help.", flush=True)


def main():
    args = parse_arguments()

    print("=" * 66)
    print(" Near-Real-Time and Periodic Data Warehouse  -  MESHJOIN")
    print("=" * 66)
    settings, online_path = ask_connection_details()

    if args.skip_prep:
        print("\n[STEP 1-2] Skipped (--skip-prep): reusing the prepared data, "
              "emptying the DW and the shed table ...")
        db.reset_for_rerun(settings)
    else:
        # Step 1
        print("\n[STEP 1] Creating the working tables and the Data Warehouse ...")
        db.create_schema(settings, args.schema)
        print(f"[STEP 1] Done. Database: {settings['database']}")

        # Step 2
        print("\n[STEP 2] Preparing the transactional data and the Master Data ...")
        customers, products, online, periodic, _ = data_prep.prepare(args.raw, online_path)
        data_prep.load_working_tables(settings, customers, products, periodic)
        del customers, products, online, periodic   # from here on the data is on disk

    control = Control(args.peak, args.non_peak, args.hour_seconds)
    control.peak = args.start == "peak"

    print("\n[SETTINGS]")
    print(f"  Stream arrival mode : starting in {control.arrival_mode()}  "
          f"(peak = {args.peak} transactions/second, "
          f"non-peak = {args.non_peak} transactions/second)")
    print(f"  One simulated hour  : {args.hour_seconds:g} seconds of real time")
    print(f"  Stream-buffer limit : {config.STREAM_BUFFER_LIMIT} transactions")
    print(f"  Master Data page    : {config.PARTITION_SIZE} tuples, "
          f"stream chunk w = {config.CHUNK_SIZE} transactions")
    print(f"  Periodic groups     : {config.PERIODIC_GROUPS}, one extracted per hour")

    # Steps 3 and 4: the threads; the MeshJoinThread also loads the DW
    print("\n[STEP 3] Starting OnlineThread, MeshJoinThread and PeriodicThread ...")
    stream_buffer = StreamBuffer(config.STREAM_BUFFER_LIMIT)
    threads = [
        MeshJoinThread(settings, control, stream_buffer),
        OnlineThread(online_path, control, stream_buffer),
        PeriodicThread(settings, control, stream_buffer),
    ]
    for thread in threads:
        thread.start()
    print(HELP_TEXT, flush=True)

    # Step 5
    command_loop(control, stream_buffer)

    log("[QUIT] Stopping the threads ...")
    control.stop.set()
    for thread in threads:
        thread.join(timeout=30)
    print_status(control, stream_buffer)
    left = control.h_size + stream_buffer.count()
    if left:
        print(f"[QUIT] {left:,} transactions were still in memory and were not loaded.")
    print("[QUIT] Program closed.")


if __name__ == "__main__":
    main()
