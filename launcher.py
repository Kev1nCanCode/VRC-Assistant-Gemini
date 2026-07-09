import os
import subprocess
from dotenv import load_dotenv, set_key

env_path = os.path.join(os.path.dirname(__file__), ".env")

def show_menu():
    load_dotenv(env_path)
    print("========================================")
    print("          VRC Assistant Launcher        ")
    print("========================================")
    api_key = os.environ.get('GEMINI_API_KEY', 'Not Set')
    api_key_display = f"{api_key[:15]}..." if len(api_key) > 15 else api_key
    print(f"1. Start Bot")
    print(f"2. Change API Key (Current: {api_key_display})")
    print(f"3. Change Input Device (Current: {os.environ.get('INPUT_DEVICE_NAME', 'Not Set')})")
    print(f"4. Change Output Device (Current: {os.environ.get('OUTPUT_DEVICE_NAME', 'Not Set')})")
    print(f"5. List Audio Devices")
    print(f"6. Exit")
    print("========================================")

def main():
    while True:
        show_menu()
        choice = input("Enter your choice: ")
        
        if choice == '1':
            print("Starting Bot...")
            subprocess.run(["python", "bot.py"])
        elif choice == '2':
            new_key = input("Enter new Gemini API Key: ")
            if new_key.strip():
                set_key(env_path, "GEMINI_API_KEY", new_key.strip())
        elif choice == '3':
            new_dev = input("Enter new Input Device Name: ")
            if new_dev.strip():
                set_key(env_path, "INPUT_DEVICE_NAME", new_dev.strip())
        elif choice == '4':
            new_dev = input("Enter new Output Device Name: ")
            if new_dev.strip():
                set_key(env_path, "OUTPUT_DEVICE_NAME", new_dev.strip())
        elif choice == '5':
            print("\nAvailable Audio Devices:")
            subprocess.run(["python", "list_devices.py"])
            print("")
        elif choice == '6':
            break
        else:
            print("Invalid choice. Please try again.")
        print("\n")

if __name__ == "__main__":
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            pass
    main()
