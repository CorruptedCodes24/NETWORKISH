import socket
import threading
import datetime
import os
import time

HOST = '0.0.0.0'
PORT = 12345
LOG_FILE = "server.log"
DATABASE_FILE = "users.txt"
DATABASE_LOCK = threading.Lock()

# Global data structures
clients = {}  # {username: socket}
usernames = {}  # {socket: username}
user_statuses = {}  # {username: status}
rooms = {}  # {room_name: [usernames]}
room_messages = {}  # {room_name: [messages]}
private_messages = {}  # {(user1, user2): [messages]}
user_profiles = {}  # {username: profile_info}
muted_users = {}  # {username: [muted_users]}
blocked_users = {}  # {username: [blocked_users]}
admin_users = set()  # Set of admin usernames

def log_message(message, level="INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{level}] {message}\n")
    print(f"[{level}] {message}")

def register_user(username, password):
    with DATABASE_LOCK:
        with open(DATABASE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{username}:{password}\n")
    log_message(f"New user registered: {username}")

def get_user_credentials():
    users = {}
    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) == 2:
                    users[parts[0]] = parts[1]
    except FileNotFoundError:
        open(DATABASE_FILE, 'w').close()  # Create file if doesn't exist
    return users

def send_message_to_client(client_socket, message):
    try:
        client_socket.sendall(f"{message}\n".encode('utf-8'))
    except Exception as e:
        log_message(f"Error sending message: {e}", "ERROR")

def is_blocked(sender, receiver):
    """Check if sender is blocked by receiver"""
    return (receiver in blocked_users and sender in blocked_users[receiver])

def send_private_message(sender_socket, sender_username, receiver_username, message):
    # Check if sender is blocked by receiver
    if is_blocked(sender_username, receiver_username):
        send_message_to_client(sender_socket, f"You are blocked by {receiver_username}.")
        return
    
    # Check if receiver has blocked sender
    if is_blocked(receiver_username, sender_username):
        send_message_to_client(sender_socket, f"You have blocked {receiver_username}.")
        return
    
    if receiver_username in clients:
        try:
            send_message_to_client(clients[receiver_username], f"(Private - {sender_username}): {message}")
            send_message_to_client(sender_socket, f"(Private to {receiver_username}): {message}")
            log_message(f"Private message: {sender_username} -> {receiver_username}: {message}")
            
            # Save message history
            key = tuple(sorted((sender_username, receiver_username)))
            if key not in private_messages:
                private_messages[key] = []
            private_messages[key].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {sender_username}: {message}")
        except Exception as e:
            log_message(f"Error sending private message: {e}", "ERROR")
            send_message_to_client(sender_socket, "Failed to send private message (user might be offline).")
    else:
        send_message_to_client(sender_socket, f"User {receiver_username} not found or offline.")

def send_user_list(client_socket):
    online_users = list(clients.keys())
    send_message_to_client(client_socket, f"Online Users: {', '.join(online_users)}")

def create_room(client_socket, username, room_name):
    if room_name not in rooms:
        rooms[room_name] = [username]
        room_messages[room_name] = []
        send_message_to_client(client_socket, f"Room '{room_name}' created.")
        log_message(f"User '{username}' created room '{room_name}'")
    else:
        send_message_to_client(client_socket, f"Room '{room_name}' already exists.")

def join_room(client_socket, username, room_name):
    if room_name in rooms:
        if username not in rooms[room_name]:
            rooms[room_name].append(username)
            send_message_to_client(client_socket, f"Joined room '{room_name}'.")
            broadcast_room_message(room_name, f"'{username}' joined the room.", sender=username)
            log_message(f"User '{username}' joined room '{room_name}'")
        else:
            send_message_to_client(client_socket, f"You're already in room '{room_name}'.")
    else:
        send_message_to_client(client_socket, f"Room '{room_name}' not found.")

def leave_room(client_socket, username, room_name):
    if room_name in rooms and username in rooms[room_name]:
        rooms[room_name].remove(username)
        send_message_to_client(client_socket, f"Left room '{room_name}'.")
        broadcast_room_message(room_name, f"'{username}' left the room.", sender=username)
        log_message(f"User '{username}' left room '{room_name}'")
        
        if not rooms[room_name]:  # If room is empty
            del rooms[room_name]
            del room_messages[room_name]
            log_message(f"Room '{room_name}' deleted (empty).")
    else:
        send_message_to_client(client_socket, f"You're not in room '{room_name}'.")

def broadcast_room_message(room_name, message, sender=None):
    if room_name in rooms:
        for user in rooms[room_name]:
            # Skip if sender is blocked by this user
            if sender and is_blocked(sender, user):
                continue
                
            if user != sender and user in clients:
                send_message_to_client(clients[user], f"[{room_name}] {message}")
                
        # Record message in room history
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if sender:
            room_messages[room_name].append(f"[{timestamp}] {sender}: {message}")
        else:
            room_messages[room_name].append(f"[{timestamp}] {message}")

def set_user_status(username, status):
    if username in user_statuses:
        user_statuses[username] = status
        broadcast_notification(f"User '{username}' status: {status}", exclude=username)
        log_message(f"User '{username}' status updated: {status}")

def broadcast_notification(message, exclude=None):
    for user, sock in clients.items():
        if user == exclude:
            continue
        send_message_to_client(sock, f"Notification: {message}")

def get_room_history(client_socket, room_name):
    if room_name in room_messages:
        send_message_to_client(client_socket, f"Room '{room_name}' history:")
        for msg in room_messages[room_name][-50:]:  # Show last 50 messages
            send_message_to_client(client_socket, f"- {msg}")
    else:
        send_message_to_client(client_socket, f"No history found for room '{room_name}'.")

def get_private_message_history(client_socket, username1, username2):
    key = tuple(sorted((username1, username2)))
    if key in private_messages:
        send_message_to_client(client_socket, f"Private messages between {username1} and {username2}:")
        for msg in private_messages[key][-50:]:  # Show last 50 messages
            send_message_to_client(client_socket, f"- {msg}")
    else:
        send_message_to_client(client_socket, f"No message history between {username1} and {username2}.")

def set_user_profile(client_socket, username, profile_info):
    user_profiles[username] = profile_info
    send_message_to_client(client_socket, "Profile updated.")
    log_message(f"User '{username}' updated profile: {profile_info}")

def get_user_profile(client_socket, target_username):
    if target_username in user_profiles:
        send_message_to_client(client_socket, f"Profile of {target_username}: {user_profiles[target_username]}")
    else:
        send_message_to_client(client_socket, f"No profile found for {target_username}.")

def mute_user(client_socket, username, target_username):
    if username not in muted_users:
        muted_users[username] = []
    if target_username not in muted_users[username]:
        muted_users[username].append(target_username)
        send_message_to_client(client_socket, f"Muted {target_username}.")
        log_message(f"User '{username}' muted '{target_username}'")
    else:
        send_message_to_client(client_socket, f"{target_username} is already muted.")

def unmute_user(client_socket, username, target_username):
    if username in muted_users and target_username in muted_users[username]:
        muted_users[username].remove(target_username)
        send_message_to_client(client_socket, f"Unmuted {target_username}.")
        log_message(f"User '{username}' unmuted '{target_username}'")
    else:
        send_message_to_client(client_socket, f"{target_username} is not muted.")

def block_user(client_socket, username, target_username):
    if username not in blocked_users:
        blocked_users[username] = []
    if target_username not in blocked_users[username]:
        blocked_users[username].append(target_username)
        send_message_to_client(client_socket, f"Blocked {target_username}.")
        log_message(f"User '{username}' blocked '{target_username}'")
    else:
        send_message_to_client(client_socket, f"{target_username} is already blocked.")

def unblock_user(client_socket, username, target_username):
    if username in blocked_users and target_username in blocked_users[username]:
        blocked_users[username].remove(target_username)
        send_message_to_client(client_socket, f"Unblocked {target_username}.")
        log_message(f"User '{username}' unblocked '{target_username}'")
    else:
        send_message_to_client(client_socket, f"{target_username} is not blocked.")

def broadcast(message, sender_socket=None, sender_username=None):
    """Broadcast to all users except sender and those who blocked sender"""
    for user, sock in clients.items():
        if sock == sender_socket:
            continue
            
        # Skip if sender is blocked by this user
        if sender_username and is_blocked(sender_username, user):
            continue
            
        try:
            send_message_to_client(sock, message)
        except:
            continue

def handle_client(client_socket, client_address):
    username = None
    print(f"New connection: {client_address}")
    log_message(f"New connection from {client_address}")
    
    try:
        # Step 1: Send authentication prompt
        send_message_to_client(client_socket, "Type '/register' to sign up or '/login' to sign in.")
        
        # Step 2: Get authentication choice
        auth_choice = client_socket.recv(1024).decode('utf-8').strip().lower()
        if not auth_choice or auth_choice not in ['/register', '/login']:
            send_message_to_client(client_socket, "Invalid choice. Disconnecting.")
            return
            
        # Step 3: Get username
        send_message_to_client(client_socket, "Enter username:")
        username_input = client_socket.recv(1024).decode('utf-8').strip()
        if not username_input:
            send_message_to_client(client_socket, "Invalid username. Disconnecting.")
            return
            
        # Step 4: Get password
        send_message_to_client(client_socket, "Enter password:")
        password_input = client_socket.recv(1024).decode('utf-8').strip()
        if not password_input:
            send_message_to_client(client_socket, "Invalid password. Disconnecting.")
            return
            
        # Step 5: Process authentication
        users = get_user_credentials()
        
        if auth_choice == '/register':
            if username_input in users:
                send_message_to_client(client_socket, "Username already taken. Disconnecting.")
                return
                
            register_user(username_input, password_input)
            send_message_to_client(client_socket, f"Registration successful! Welcome {username_input}.")
            log_message(f"New user registered: {username_input}")
            
        elif auth_choice == '/login':
            if username_input not in users or users[username_input] != password_input:
                send_message_to_client(client_socket, "Invalid username or password. Disconnecting.")
                return
                
            if username_input in clients:
                send_message_to_client(client_socket, "User already logged in from another device.")
                return
                
            send_message_to_client(client_socket, f"Login successful! Welcome back {username_input}.")
            log_message(f"User logged in: {username_input}")
            
        # Finalize authentication
        usernames[client_socket] = username_input
        clients[username_input] = client_socket
        user_statuses[username_input] = "Online"
        username = username_input
        broadcast(f"'{username}' joined the chat!", sender_socket=client_socket, sender_username=username)
        log_message(f"User '{username}' authenticated successfully")
        
        # Main command loop
        while True:
            try:
                command = client_socket.recv(1024).decode('utf-8').strip()
                if not command:
                    break
                    
                if command == "/quit":
                    send_message_to_client(client_socket, "Goodbye!")
                    break
                    
                elif command == "/list":
                    send_user_list(client_socket)
                    
                elif command.startswith("/private"):
                    parts = command.split(maxsplit=2)
                    if len(parts) == 3:
                        receiver_username = parts[1]
                        private_message = parts[2]
                        send_private_message(client_socket, username, receiver_username, private_message)
                    else:
                        send_message_to_client(client_socket, "Usage: /private <username> <message>")
                        
                elif command.startswith("/create_room"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        room_name = parts[1]
                        create_room(client_socket, username, room_name)
                    else:
                        send_message_to_client(client_socket, "Usage: /create_room <room_name>")
                        
                elif command.startswith("/join"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        room_name = parts[1]
                        join_room(client_socket, username, room_name)
                    else:
                        send_message_to_client(client_socket, "Usage: /join <room_name>")
                        
                elif command.startswith("/leave"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        room_name = parts[1]
                        leave_room(client_socket, username, room_name)
                    else:
                        send_message_to_client(client_socket, "Usage: /leave <room_name>")
                        
                elif command.startswith("/room_history"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        room_name = parts[1]
                        get_room_history(client_socket, room_name)
                    else:
                        send_message_to_client(client_socket, "Usage: /room_history <room_name>")
                        
                elif command.startswith("/pm_history"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        other_user = parts[1]
                        get_private_message_history(client_socket, username, other_user)
                    else:
                        send_message_to_client(client_socket, "Usage: /pm_history <username>")
                        
                elif command.startswith("/set_profile"):
                    profile_info = command[len("/set_profile "):].strip()
                    if profile_info:
                        set_user_profile(client_socket, username, profile_info)
                    else:
                        send_message_to_client(client_socket, "Usage: /set_profile <profile_info>")
                        
                elif command.startswith("/profile"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        target_username = parts[1]
                        get_user_profile(client_socket, target_username)
                    else:
                        send_message_to_client(client_socket, "Usage: /profile <username>")
                        
                elif command.startswith("/mute"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        target_username = parts[1]
                        mute_user(client_socket, username, target_username)
                    else:
                        send_message_to_client(client_socket, "Usage: /mute <username>")
                        
                elif command.startswith("/unmute"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        target_username = parts[1]
                        unmute_user(client_socket, username, target_username)
                    else:
                        send_message_to_client(client_socket, "Usage: /unmute <username>")
                        
                elif command.startswith("/block"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        target_username = parts[1]
                        block_user(client_socket, username, target_username)
                    else:
                        send_message_to_client(client_socket, "Usage: /block <username>")
                        
                elif command.startswith("/unblock"):
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        target_username = parts[1]
                        unblock_user(client_socket, username, target_username)
                    else:
                        send_message_to_client(client_socket, "Usage: /unblock <username>")
                        
                elif command == "/status online":
                    set_user_status(username, "Online")
                elif command == "/status busy":
                    set_user_status(username, "Busy")
                elif command == "/status dnd":
                    set_user_status(username, "Do Not Disturb")
                elif command == "/status offline":
                    set_user_status(username, "Offline")
                else:
                    # Check if message is for a room
                    if command.startswith("/"):
                        send_message_to_client(client_socket, "Unknown command. Type /help for available commands.")
                        continue
                    
                    # Check if user is in any rooms
                    in_room = False
                    for room_name, members in rooms.items():
                        if username in members:
                            in_room = True
                            # Send message to room
                            broadcast_room_message(room_name, command, sender=username)
                    
                    # If not in any room, broadcast to general chat
                    if not in_room:
                        broadcast(f"[{username}]: {command}", 
                                 sender_socket=client_socket, 
                                 sender_username=username)
                    
            except ConnectionResetError:
                break
            except Exception as e:
                log_message(f"Error handling command from {username}: {e}", "ERROR")
                break

    except Exception as e:
        log_message(f"Client error: {e}", "ERROR")
    finally:
        if username:
            # Cleanup user data
            if username in clients:
                del clients[username]
            if username in user_statuses:
                del user_statuses[username]
                
            # Leave all rooms
            for room_name, users in list(rooms.items()):
                if username in users:
                    users.remove(username)
                    broadcast_room_message(room_name, f"'{username}' left the room.", sender=username)
                    if not users:  # Delete empty rooms
                        del rooms[room_name]
                        del room_messages[room_name]
                        log_message(f"Room '{room_name}' deleted (empty).")
            
            log_message(f"User '{username}' disconnected")
            broadcast(f"'{username}' left the chat.", 
                     sender_username=username, 
                     exclude=username)
            
        if client_socket in usernames:
            del usernames[client_socket]
            
        client_socket.close()
        print(f"Connection closed: {client_address}")

def main():
    # Create necessary files if they don't exist
    if not os.path.exists(DATABASE_FILE):
        open(DATABASE_FILE, 'w').close()
    if not os.path.exists(LOG_FILE):
        open(LOG_FILE, 'w').close()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        print(f"Server listening on {HOST}:{PORT}")
        log_message(f"Server started on {HOST}:{PORT}")
        
        while True:
            client_socket, client_address = server_socket.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address))
            client_thread.daemon = True
            client_thread.start()
            print(f"New connection from {client_address}")
            log_message(f"New connection from {client_address}")
            
    except KeyboardInterrupt:
        print("\nServer shutting down...")
        log_message("Server shut down by admin")
    except Exception as e:
        print(f"Server error: {e}")
        log_message(f"Server error: {e}", "CRITICAL")
    finally:
        server_socket.close()
        print("Server closed.")

if __name__ == "__main__":
    main()