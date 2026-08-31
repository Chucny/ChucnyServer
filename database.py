from pathlib import Path
import mariadb


from config import settings


# =========================
# CONFIG
# =========================

DATABASE_HOST = settings.get("host", "localhost")
DATABASE_PORT = settings.get("port", 3306)
DATABASE_NAME = settings.get("name")
DATABASE_USER = settings.get("user")
DATABASE_PASSWORD = settings.get("password")


# =========================
# CHUCNYSERVER FILE LOCATION
# =========================

BASE_DIR = Path("/chucnyserver")


client = mariadb.connect(
    host=DATABASE_HOST,
    port=int(DATABASE_PORT),
    user=DATABASE_USER,
    password=DATABASE_PASSWORD,
    database=DATABASE_NAME
)


# =========================
# easy function that saves a file
# =========================

def backup_file(file_path, collection_name):
    file_path = BASE_DIR / file_path

    content = file_path.read_text(encoding="utf-8")

    cursor = client.cursor()

    # collection_name is not really needed in MariaDB
    # since we are storing everything in one table
    cursor.execute(
        """
        INSERT INTO files (path, content)
        VALUES (?, ?)

        ON DUPLICATE KEY UPDATE
        content = VALUES(content)
        """,
        (
            str(file_path),
            content
        )
    )

    client.commit()
    cursor.close()


# =========================
# this is just a simple function to back up the whole saves folder.
# =========================

def backup_saves_folder():
    saves_folder = BASE_DIR / "saves"

    cursor = client.cursor()

    for file_path in saves_folder.rglob("*"):

        if not file_path.is_file():
            continue

        relative_path = str(file_path.relative_to(BASE_DIR))

        content = file_path.read_text(encoding="utf-8")

        cursor.execute(
            """
            INSERT INTO files (path, content)
            VALUES (?, ?)

            ON DUPLICATE KEY UPDATE
            content = VALUES(content)
            """,
            (
                relative_path,
                content
            )
        )

    client.commit()
    cursor.close()

    print("Saves folder backed up successfully.")


# now just writing out of pure vibe
# i would say theres nothing wrong with this since im not using ai
# lets back up the gyms, places and settings ez


def backup_main_files():

    backup_file("gyms.json", "gyms")
    backup_file("settings.json", "settings")
    backup_file("places.json", "places")
    print("Main JSON files backed up successfully.")


# =========================
# and finally, back up everything ez
# =========================

def backup_all():

    backup_saves_folder()
    backup_main_files()

    print("Everything backed up to MariaDB.")




# now, lets get to the second part of the code
# this imports from mariadb. i didnt make a second script for this, i was too lazy



import shutil
from pathlib import Path


def restore_all():

    saves_folder = BASE_DIR / "saves"

    # Delete the current saves folder
    if saves_folder.exists():
        shutil.rmtree(saves_folder)

    # Create a new empty saves folder
    saves_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    cursor = client.cursor()

    # =========================
    # IMPORT SAVES FOLDER
    # =========================

    cursor.execute(
        """
        SELECT path, content
        FROM files
        WHERE path LIKE 'saves/%'
        """
    )

    documents = cursor.fetchall()

    for document in documents:

        database_path = document[0]
        content = document[1]

        # remove "saves/" from the beginning
        relative_path = database_path.removeprefix("saves/")

        file_path = saves_folder / relative_path

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file_path.write_text(
            content,
            encoding="utf-8"
        )

    # =========================
    # IMPORT GYMS, SETTINGS AND PLACES
    # =========================

    for file_name in ["gyms.json", "settings.json", "places.json"]:

        cursor.execute(
            """
            SELECT content
            FROM files
            WHERE path = ?
            """,
            (file_name,)
        )

        document = cursor.fetchone()

        if document is None:
            print(f"{file_name} was not found in the database.")
            continue

        content = document[0]

        file_path = BASE_DIR / file_name

        file_path.write_text(
            content,
            encoding="utf-8"
        )

        print(f"{file_name} imported!")

    cursor.close()

    print("Everything imported!")




# now lets finally make an easy interface. why not? better than doing anything manually since this will be much more friendly for the users


HELP_MESSAGE = """
Commands:
- /import imports data from MariaDB
- /backup_all backs up everything to MariaDB
- /backup_main_files backs up everything else than player data to MariaDB"""


def command(command):
    if command == "/help":
        print(HELP_MESSAGE)

    elif command == "/import":
        restore_all()

    elif command == "/backup_main_files":
        backup_main_files()

    elif command == "/backup_all":
        backup_all()

    else:
        print("Unknown command, type /help for help")


def db_interface():
    while "CAF is retarded" == "CAF is retarded":
        _COMMAND = input("MariaDB> ")
        command(_COMMAND)


# now lets finally start the interface im so done with coding this

db_interface()