import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import socket
import threading
import json
import os
from PIL import Image, ImageTk  # pip install pillow

PORT = 5050
BUFFER_SIZE = 1024
DATA_FILE = "lan_messenger_data.json"

# ---- App runtime flags / objects ----
STOP_EVENT = threading.Event()   # for clean shutdown of server loop
SERVER_SOCKET = None             # we keep a reference to close it on exit

# ---- Persistent data ----
def _default_data():
    return {"contacts": {}, "chat_history": {}, "icons": {}}

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # sanity check minimal structure
            if not isinstance(data, dict):
                data = _default_data()
            for key in ["contacts", "chat_history", "icons"]:
                if key not in data or not isinstance(data[key], dict):
                    data[key] = {}
    except Exception:
        data = _default_data()
else:
    data = _default_data()

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

# ===== SOCKET SERVER (runs in background thread) =====
def start_server():
    global SERVER_SOCKET
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    SERVER_SOCKET = server
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("", PORT))
        server.listen()
        server.settimeout(1)  # allows checking STOP_EVENT
    except Exception as e:
        print(f"Server error: {e}")
        return

    while not STOP_EVENT.is_set():
        try:
            conn, addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            # socket closed during shutdown
            break

        try:
            incoming = conn.recv(BUFFER_SIZE)
            if not incoming:
                conn.close()
                continue
            try:
                incoming_str = incoming.decode(errors="ignore")
            except Exception:
                incoming_str = ""
            if ":" not in incoming_str:
                conn.close()
                continue

            username, msg = incoming_str.split(":", 1)
            username = username.strip()
            msg = msg.strip()

            timestamp_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            timestamp_short = datetime.datetime.now().strftime("%H:%M")

            # Update contacts and history
            if username:
                if username not in data["contacts"]:
                    data["contacts"][username] = addr[0]
                if username not in data["chat_history"]:
                    data["chat_history"][username] = []
                data["chat_history"][username].append({
                    "sender": username,
                    "text": msg,
                    "time": timestamp_full
                })
                save_data()

                # Thread-safe UI update
                try:
                    if contact_var.get() == username:
                        root.after(0, insert_message, username, msg, timestamp_short)
                    else:
                        # If it's a new contact or not selected, refresh contact list highlight/update
                        root.after(0, refresh_contacts)
                except Exception:
                    # UI might be gone during shutdown; ignore
                    pass
            conn.close()
        except Exception as e:
            # Ignore errors during shutdown; log otherwise
            if not STOP_EVENT.is_set():
                print(f"Server loop error: {e}")
            try:
                conn.close()
            except Exception:
                pass

    # Cleanup
    try:
        server.close()
    except Exception:
        pass
    SERVER_SOCKET = None

# ===== MESSAGE SENDING (UI thread) =====
def send_message(event=None):
    username = contact_var.get()
    if not username:
        messagebox.showerror("Error", "Select a contact first.")
        return
    if username not in data["contacts"]:
        messagebox.showerror("Error", "Unknown contact IP.")
        return

    msg = msg_entry.get().strip()
    if not msg:
        return

    try:
        ip = data["contacts"][username]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ip, PORT))
        s.send(f"{my_username}:{msg}".encode())
        s.close()

        timestamp_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp_short = datetime.datetime.now().strftime("%H:%M")

        if username not in data["chat_history"]:
            data["chat_history"][username] = []
        data["chat_history"][username].append({
            "sender": my_username,
            "text": msg,
            "time": timestamp_full
        })
        save_data()

        insert_message(my_username, msg, timestamp_short)
        msg_entry.delete(0, tk.END)

    except Exception as e:
        messagebox.showerror("Error", f"Could not send message: {e}")

# ===== ICON LOADING =====
def load_icon(username, size=32):
    try:
        if username in data["icons"] and os.path.exists(data["icons"][username]):
            img = Image.open(data["icons"][username])
        else:
            img = Image.new("RGB", (size, size), color="#7289DA")  # default icon
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        # fallback to a solid icon if image fails
        img = Image.new("RGB", (size, size), color="#7289DA")
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

# ===== ADD CONTACT =====
def add_contact():
    name = simpledialog.askstring("Add Contact", "Enter contact username:")
    if not name:
        return
    ip = simpledialog.askstring("Add Contact", "Enter contact IP address:")
    if not ip:
        return

    icon_path = filedialog.askopenfilename(
        title="Choose Contact Icon",
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif")]
    )
    if icon_path:
        data["icons"][name] = icon_path
    data["contacts"][name] = ip
    if name not in data["chat_history"]:
        data["chat_history"][name] = []
    save_data()
    refresh_contacts()

# ===== REFRESH CONTACTS =====
def refresh_contacts():
    # only safe to call from UI thread
    for widget in contact_list_frame.winfo_children():
        widget.destroy()
    for name in sorted(data["contacts"].keys()):
        frame = tk.Frame(contact_list_frame, bg=BG_COLOR)
        frame.pack(fill="x", pady=2)

        icon_img = load_icon(name)
        lbl_icon = tk.Label(frame, image=icon_img, bg=BG_COLOR)
        lbl_icon.image = icon_img
        lbl_icon.pack(side="left", padx=5)

        btn = tk.Button(frame, text=name, font=("Segoe UI", 10),
                        fg="white", bg=BG_COLOR, activebackground="#99AAB5",
                        relief="flat", command=lambda n=name: select_contact(n))
        btn.pack(side="left", fill="x", expand=True)

# ===== SELECT CONTACT =====
def select_contact(name):
    contact_var.set(name)
    load_chat_history()

# ===== LOAD CHAT HISTORY =====
def load_chat_history():
    chat_log.config(state="normal")
    chat_log.delete(1.0, tk.END)
    username = contact_var.get()
    if username in data["chat_history"]:
        for msg in data["chat_history"][username]:
            full_time = msg.get("time", "")
            try:
                time_display = datetime.datetime.strptime(full_time, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except Exception:
                time_display = "??:??"
            insert_message(msg.get("sender", "Unknown"), msg.get("text", ""), time_display)
    chat_log.config(state="disabled")

# ===== INSERT MESSAGE WITH ICON & TIME =====
def insert_message(sender, text, time_str):
    # must be called on UI thread (we ensure that with root.after from server)
    if not chat_log.winfo_exists():
        return
    chat_log.config(state="normal")
    icon_img = load_icon(sender, size=24)
    chat_log.image_create(tk.END, image=icon_img)
    chat_log.insert(tk.END, f" {sender} [{time_str}]: {text}\n")
    # prevent image GC
    chat_log.image_store = getattr(chat_log, "image_store", []) + [icon_img]
    chat_log.config(state="disabled")
    # auto-scroll to end
    chat_log.see(tk.END)

# ===== APP INIT =====
root = tk.Tk()
root.withdraw()
my_username = simpledialog.askstring("Your Username", "Enter your username:")
root.deiconify()
if not my_username:
    messagebox.showerror("Error", "Username is required!")
    root.destroy()
    raise SystemExit()

# Theme colors
BG_COLOR = "#2C2F33"
MSG_BG = "#23272A"
BTN_COLOR = "#7289DA"
TEXT_COLOR = "#FFFFFF"

root.title(f"LAN Messenger - {my_username}")
root.geometry("700x500")
root.configure(bg=BG_COLOR)

# ===== DELETE CONTACT =====
def delete_contact():
    name = contact_var.get()
    if not name:
        messagebox.showerror("Error", "No contact selected.")
        return
    confirm = messagebox.askyesno("Delete Contact", f"Are you sure you want to delete '{name}'?")
    if confirm:
        if name in data["contacts"]:
            del data["contacts"][name]
        if name in data["chat_history"]:
            del data["chat_history"][name]
        if name in data["icons"]:
            del data["icons"][name]
        save_data()
        contact_var.set("")
        refresh_contacts()
        chat_log.config(state="normal")
        chat_log.delete(1.0, tk.END)
        chat_log.config(state="disabled")
        messagebox.showinfo("Deleted", f"Contact '{name}' has been deleted.")

# ===== CONTACT SIDEBAR =====
contact_frame = tk.Frame(root, bg=BG_COLOR, width=180)
contact_frame.pack(side="left", fill="y")

contact_title = tk.Label(contact_frame, text="Contacts", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 12, "bold"))
contact_title.pack(pady=5)

contact_list_frame = tk.Frame(contact_frame, bg=BG_COLOR)
contact_list_frame.pack(fill="y", expand=True)

add_contact_btn = tk.Button(contact_frame, text="+ Add", bg=BTN_COLOR, fg="white", relief="flat",
                            font=("Segoe UI", 10), command=add_contact)
add_contact_btn.pack(fill="x", pady=(5, 2))

delete_contact_btn = tk.Button(contact_frame, text="– Delete", bg="#FF5555", fg="white", relief="flat",
                               font=("Segoe UI", 10), command=delete_contact)
delete_contact_btn.pack(fill="x", pady=(0, 5))

# ===== Chat area =====
chat_frame = tk.Frame(root, bg=MSG_BG)
chat_frame.pack(side="right", fill="both", expand=True)

chat_log = tk.Text(chat_frame, bg=MSG_BG, fg=TEXT_COLOR, font=("Segoe UI", 10),
                   relief="flat", wrap="word", state="disabled")
chat_log.pack(fill="both", expand=True, pady=(5, 0), padx=5)

msg_frame = tk.Frame(chat_frame, bg=MSG_BG)
msg_frame.pack(fill="x", pady=5)

msg_entry = tk.Entry(msg_frame, font=("Segoe UI", 10), bg="#99AAB5", fg="black", relief="flat")
msg_entry.pack(side="left", fill="x", expand=True, padx=(5, 2), pady=2)
msg_entry.bind("<Return>", send_message)  # Press Enter to send

send_btn = tk.Button(msg_frame, text="Send", bg=BTN_COLOR, fg="white", relief="flat",
                     font=("Segoe UI", 10, "bold"), command=send_message)
send_btn.pack(side="right", padx=(2, 5), pady=2)

contact_var = tk.StringVar(root)
refresh_contacts()

# ===== Graceful close handler =====
def on_closing():
    # stop server loop and close socket
    STOP_EVENT.set()
    try:
        if SERVER_SOCKET is not None:
            try:
                SERVER_SOCKET.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                SERVER_SOCKET.close()
            except Exception:
                pass
    except Exception:
        pass
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

# Start server thread
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

root.mainloop()