import os
import time

import mysql.connector
from mysql.connector import Error


def get_db_connection():
    """
    Tworzy połączenie z MySQL.
    """

    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def wait_for_mysql(max_attempts=10, delay=3):
    """
    Czeka, aż MySQL będzie dostępny.
    """

    for attempt in range(1, max_attempts + 1):

        try:
            connection = get_db_connection()

            if connection.is_connected():

                connection.close()

                print(
                    "Połączenie z MySQL: OK"
                )

                return True

        except Error as error:

            print(
                f"MySQL niedostępny "
                f"(próba {attempt}/{max_attempts}): "
                f"{error}"
            )

            if attempt < max_attempts:
                time.sleep(delay)

    return False


def save_job(job):
    """
    Dodaje nową ofertę albo aktualizuje istniejącą.

    Unikalność:
        portal + source_id

    Nowa oferta:
        first_seen_at = NOW()
        last_seen_at = NOW()

    Istniejąca:
        first_seen_at bez zmian
        last_seen_at = NOW()
        is_active = 1
    """

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        sql = """
            INSERT INTO jobs (
                portal,
                source_id,
                title,
                company,
                location,
                work_mode,
                salary,
                url,
                keyword,
                published_at,
                first_seen_at,
                last_seen_at,
                is_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW(),
                NOW(),
                1
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                company = VALUES(company),
                location = VALUES(location),
                work_mode = VALUES(work_mode),
                salary = VALUES(salary),
                url = VALUES(url),
                keyword = VALUES(keyword),
                published_at = VALUES(published_at),
                last_seen_at = NOW(),
                is_active = 1
        """

        values = (
            job["portal"],
            job["source_id"],
            job["title"],
            job["company"],
            job["location"],
            job["work_mode"],
            job["salary"],
            job["url"],
            job["keyword"],
            job["published_at"],
        )

        cursor.execute(
            sql,
            values,
        )

        connection.commit()

        if cursor.rowcount == 1:

            print(
                f"[NOWA] {job['title']}"
            )

        else:

            print(
                f"[AKTUALIZACJA] {job['title']}"
            )

    finally:

        connection.close()