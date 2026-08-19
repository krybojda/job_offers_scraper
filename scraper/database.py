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
    Czeka na dostępność MySQL.
    """

    for attempt in range(1, max_attempts + 1):

        try:
            connection = get_db_connection()

            if connection.is_connected():
                connection.close()

                print("Połączenie z MySQL: OK")

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

    Zwraca:
        {
            "is_new": bool,
            "needs_details": bool
        }

    Nowa oferta:
        first_seen_at = NOW()
        last_seen_at = NOW()
        missed_count = 0
        is_active = 1

    Istniejąca oferta:
        first_seen_at pozostaje bez zmian
        last_seen_at = NOW()
        missed_count = 0
        is_active = 1
    """

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # -------------------------------------------------
        # Czy oferta już istnieje?
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT details_scraped_at
            FROM jobs
            WHERE portal = %s
              AND source_id = %s
            LIMIT 1
            """,
            (
                job["portal"],
                job["source_id"],
            ),
        )

        existing = cursor.fetchone()

        is_new = existing is None

        needs_details = (
            is_new
            or existing[0] is None
        )

        # -------------------------------------------------
        # INSERT / UPDATE
        # -------------------------------------------------

        sql = """
            INSERT INTO jobs (
                portal,
                source_id,
                title,
                company,
                location,
                work_mode,
                work_type,
                experience_level,
                contract_type,
                salary,
                url,
                keyword,
                published_at,
                first_seen_at,
                last_seen_at,
                is_active,
                missed_count
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                NULL,
                NULL,
                %s,
                %s,
                %s,
                %s,
                NOW(),
                NOW(),
                1,
                0
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                company = VALUES(company),
                location = VALUES(location),
                work_mode = VALUES(work_mode),
                work_type = VALUES(work_type),
                salary = VALUES(salary),
                url = VALUES(url),
                keyword = VALUES(keyword),
                published_at = VALUES(published_at),
                last_seen_at = NOW(),
                is_active = 1,
                missed_count = 0
        """

        values = (
            job["portal"],
            job["source_id"],
            job["title"],
            job["company"],
            job["location"],
            job["work_mode"],
            job["work_type"],
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

        if is_new:
            print(
                f"[NOWA] {job['title']}"
            )
        else:
            print(
                f"[AKTUALIZACJA] "
                f"{job['title']}"
            )

        return {
            "is_new": is_new,
            "needs_details": needs_details,
        }

    finally:

        connection.close()


def save_job_details(
    portal,
    source_id,
    details,
):
    """
    Zapisuje szczegółowe informacje o ofercie.
    """

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        sql = """
            UPDATE jobs
            SET
                title = COALESCE(%s, title),
                company = COALESCE(%s, company),
                location = COALESCE(%s, location),
                work_mode = COALESCE(%s, work_mode),
                work_type = COALESCE(%s, work_type),
                experience_level = COALESCE(%s, experience_level),
                contract_type = COALESCE(%s, contract_type),
                salary = COALESCE(%s, salary),
                job_description = %s,
                tech_stack = %s,
                office_location = %s,
                about_company = %s,
                expires_text = %s,
                expires_at = %s,
                details_scraped_at = NOW()
            WHERE portal = %s
              AND source_id = %s
        """

        values = (
            details.get("title"),
            details.get("company"),
            details.get("location"),
            details.get("work_mode"),
            details.get("work_type"),
            details.get("experience_level"),
            details.get("contract_type"),
            details.get("salary"),
            details.get("job_description"),
            details.get("tech_stack"),
            details.get("office_location"),
            details.get("about_company"),
            details.get("expires_text"),
            details.get("expires_at"),
            portal,
            source_id,
        )

        cursor.execute(
            sql,
            values,
        )

        connection.commit()

        print(
            f"[SZCZEGÓŁY] zapisano: {source_id}"
        )

    finally:

        connection.close()


def mark_missing_jobs(
    portal,
    seen_source_ids,
    threshold=3,
):
    """
    Aktualizuje missed_count dla ofert,
    których nie znaleziono w pełnym przebiegu.

    Funkcja powinna być wywoływana tylko wtedy,
    gdy cały skan danego portalu zakończył się poprawnie.
    """

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # -------------------------------------------------
        # Oferty znalezione:
        # reset missed_count i aktywność.
        # -------------------------------------------------

        if seen_source_ids:

            source_ids = list(
                seen_source_ids
            )

            placeholders = ",".join(
                ["%s"] * len(source_ids)
            )

            sql_seen = f"""
                UPDATE jobs
                SET
                    missed_count = 0,
                    is_active = 1
                WHERE portal = %s
                  AND source_id IN (
                      {placeholders}
                  )
            """

            cursor.execute(
                sql_seen,
                [portal] + source_ids,
            )

            # -------------------------------------------------
            # Aktywne oferty, których nie znaleziono:
            # missed_count + 1
            # -------------------------------------------------

            sql_missing = f"""
                UPDATE jobs
                SET
                    missed_count = missed_count + 1
                WHERE portal = %s
                  AND is_active = 1
                  AND source_id NOT IN (
                      {placeholders}
                  )
            """

            cursor.execute(
                sql_missing,
                [portal] + source_ids,
            )

        else:

            # Jeżeli pełny skan nie zwrócił żadnej oferty,
            # zwiększamy missed_count wszystkim aktywnym.
            cursor.execute(
                """
                UPDATE jobs
                SET
                    missed_count = missed_count + 1
                WHERE portal = %s
                  AND is_active = 1
                """,
                (portal,),
            )

        # -------------------------------------------------
        # Oznacz nieaktywne po przekroczeniu progu.
        # -------------------------------------------------

        cursor.execute(
            """
            UPDATE jobs
            SET is_active = 0
            WHERE portal = %s
              AND missed_count >= %s
            """,
            (
                portal,
                threshold,
            ),
        )

        connection.commit()

        print(
            "[AKTYWNOŚĆ] "
            f"zaktualizowano portal: {portal}"
        )

    finally:

        connection.close()