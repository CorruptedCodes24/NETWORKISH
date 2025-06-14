import socket
import threading
import sys
import getpass

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 12345

class ChatClient:
    def __init__(self):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.username = None
        self.running = False
        self.current_room = None

    def receive_messages(self):
        """Handle incoming messages from the server"""
        while self.running:
            try:
                message = self.client_socket.recv(1024).decode('utf-8')
                if not message:
                    print("\nServer closed the connection.")
                    self.running = False
                    break
                print(f"\n{message}")
                sys.stdout.write("> ")
                sys.stdout.flush()
            except ConnectionResetError:
                print("\nServer connection was reset.")
                self.running = False
                break
            except Exception as e:
                print(f"\nError receiving message: {e}")
                self.running = False
                break

    def send_command(self, command):
        """Send a command to the server"""
        try:
            self.client_socket.sendall(command.encode('utf-8'))
        except Exception as e:
            print(f"Error sending command: {e}")
            self.running = False

    def handle_input(self):
        """Handle user input and send commands to server"""
        while self.running:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue

                if user_input.lower() == '/quit':
                    self.running = False
                    self.send_command('/quit')
                    break
                elif user_input.lower() == '/help':
                    self.show_help()
                else:
                    self.send_command(user_input)

            except KeyboardInterrupt:
                print("\nUse '/quit' to exit properly.")
            except Exception as e:
                print(f"Error handling input: {e}")
                self.running = False
                break

    def show_help(self):
        """Display available commands"""
        help_text = """
Available Commands:
/help - Show this help message
/quit - Exit the chat
/list - List online users
/private <username> <message> - Send private message
/create_room <room_name> - Create a new chat room
/join <room_name> - Join a chat room
/leave <room_name> - Leave a chat room
/room_history <room_name> - View room message history
/pm_history <username> - View private message history
/set_profile <info> - Set your profile info
/profile <username> - View user's profile
/mute <username> - Mute a user
/unmute <username> - Unmute a user
/block <username> - Block a user
/unblock <username> - Unblock a user
/status [online|busy|dnd|offline] - Set your status
"""
        print(help_text)

    def authenticate(self):
        """Handle authentication with the server"""
        try:
            # Get initial server prompt
            initial_prompt = self.client_socket.recv(1024).decode('utf-8').strip()
            print(initial_prompt)
            
            while True:
                command = input("Enter command (/register or /login): ").lower()
                if command in ['/register', '/login']:
                    self.send_command(command)
                    break
                print("Invalid command. Please enter /register or /login")
            
            # Get username prompt
            username_prompt = self.client_socket.recv(1024).decode('utf-8').strip()
            print(username_prompt)
            username = input("Username: ")
            self.send_command(username)
            
            # Get password prompt
            password_prompt = self.client_socket.recv(1024).decode('utf-8').strip()
            print(password_prompt)
            password = getpass.getpass("Password: ")
            self.send_command(password)
            
            # Get authentication result
            auth_result = self.client_socket.recv(1024).decode('utf-8').strip()
            print(auth_result)
            
            if "successful" in auth_result.lower():
                self.username = username
                return True
            
            return False
        
        except Exception as e:
            print(f"Authentication error: {e}")
            return False

    def start(self):
        """Start the client"""
        try:
            self.client_socket.connect((SERVER_HOST, SERVER_PORT))
            print(f"Connected to server at {SERVER_HOST}:{SERVER_PORT}")
            
            # Handle authentication
            if not self.authenticate():
                self.client_socket.close()
                return
            
            # Start message threads
            self.running = True
            receive_thread = threading.Thread(target=self.receive_messages)
            input_thread = threading.Thread(target=self.handle_input)
            
            receive_thread.daemon = True
            input_thread.daemon = True
            
            receive_thread.start()
            input_thread.start()
            
            print("\nType /help to see available commands")
            print("> ", end="", flush=True)
            
            receive_thread.join()
            input_thread.join()
            
        except ConnectionRefusedError:
            print(f"Connection refused. Make sure the server is running on {SERVER_HOST}:{SERVER_PORT}")
        except socket.gaierror:
            print(f"Invalid server address: {SERVER_HOST}")
        except Exception as e:
            print(f"Client error: {e}")
        finally:
            self.running = False
            self.client_socket.close()
            print("Disconnected from server.")

if __name__ == "__main__":
    client = ChatClient()
    client.start()
