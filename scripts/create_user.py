import getpass

from sqlmodel import Session
from pydantic import ValidationError
from database.db_engine import engine
from database.models.user import User
from repository.user_repository import UserRepository
from dto.request.create_user_request import CreateUserRequest
from auth.password import hash_password

def main():

    print("Create Makeway user")
    print("--------------------")

    email = input("Email: ").strip().lower()

    if not email:
        print("Email cannot be empty.")
        return

    password = getpass.getpass("Password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if password != confirm_password:
        print("Passwords do not match.")
        return

    try:
        request = CreateUserRequest(
            email=email,
            password=password
        )
    except ValidationError as exc:
        print("Invalid user data:")

        for error in exc.errors():
            print(
                f"- {error['loc'][0]}: {error['msg']}"
            )

        return


    with Session(engine) as session:

        repository = UserRepository(session)

        existing_user = repository.get_by_email(email)

        if existing_user:
            print(f"User already exists: {email}")
            return

        
        user = User(
            email=request.email,
            passwordHash=hash_password(request.password),
            createdBy="SYSTEM",
            modifiedBy="SYSTEM"
        )

        user = repository.create(user)

        print()
        print("User created successfully.")
        print(f"User ID: {user.userId}")
        print(f"Email: {user.email}")


if __name__ == "__main__":
    main()