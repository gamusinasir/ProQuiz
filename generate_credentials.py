import os
import secrets
import hashlib
from getpass import getpass

def generate_credentials():
    # Generate a secure random salt
    salt = secrets.token_hex(16)
    
    # Get username and PIN from user input
    username = input("Enter super admin username: ")
    while True:
        pin = getpass("Enter 6-digit PIN: ")
        if len(pin) == 6 and pin.isdigit():
            break
        print("PIN must be exactly 6 digits")
    
    # Hash the PIN with salt
    hashed_pin = hashlib.sha256((pin + salt).encode()).hexdigest()
    
    # Create .env content
    env_content = f"""# Super Admin Credentials
SUPER_ADMIN_USERNAME="{username}"
SUPER_ADMIN_PIN_HASH="{hashed_pin}"
SUPER_ADMIN_SALT="{salt}"
"""
    
    # Write to .env file
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("\nCredentials generated and saved to .env file")
    print(f"Username: {username}")
    print("PIN: ******")
    print("\nKeep these credentials safe!")

if __name__ == "__main__":
    generate_credentials()
