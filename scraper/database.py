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

    Szczegóły nigdy nie są kasowane podczas aktualizacji.
    """

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

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
                f"[AKTUALIZACJA] {job['title']}"
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

    details_scraped_at jest ustawiane TYLKO wtedy,
    gdy strona szczegółowa została poprawnie odczytana
    i otrzymaliśmy wynik details.
    """

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        sql = """
            UPDATE jobs
            SET
                title = COALESCE(NULLIF(%s, ''), title),
                company = COALESCE(NULLIF(%s, ''), company),
                location = COALESCE(NULLIF(%s, ''), location),
                work_mode = COALESCE(NULLIF(%s, ''), work_mode),
                work_type = COALESCE(NULLIF(%s, ''), work_type),
                experience_level = COALESCE(NULLIF(%s, ''), experience_level),
                contract_type = COALESCE(NULLIF(%s, ''), contract_type),
                salary = COALESCE(NULLIF(%s, ''), salary),
                published_at = COALESCE(%s, published_at),
                job_description = COALESCE(NULLIF(%s, ''), job_description),
                tech_stack = COALESCE(NULLIF(%s, ''), tech_stack),
                office_location = COALESCE(NULLIF(%s, ''), office_location),
                about_company = COALESCE(NULLIF(%s, ''), about_company),
                expires_text = COALESCE(NULLIF(%s, ''), expires_text),
                expires_at = COALESCE(%s, expires_at),
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
            details.get("published_at"),
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

        if cursor.rowcount == 0:
            raise RuntimeError(
                "Nie znaleziono oferty do aktualizacji: "
                f"portal={portal}, source_id={source_id}"
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


def get_jobs_without_details(
    portal,
    limit=20,
):
    """
    Pobiera oferty, które nie mają jeszcze
    details_scraped_at.

    Zwraca wyłącznie rekordy rzeczywiście istniejące
    w bazie i sortuje je od najstarszych ID.
    """

    connection = get_db_connection()

    try:
        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
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
                published_at
            FROM jobs
            WHERE portal = %s
              AND details_scraped_at IS NULL
              AND is_active = 1
            ORDER BY id ASC
            LIMIT %s
            """,
            (
                portal,
                int(limit),
            ),
        )

        jobs = cursor.fetchall()

        print(
            f"[SZCZEGÓŁY] DB zwróciła: "
            f"{len(jobs)} ofert bez szczegółów "
            f"dla portalu {portal}"
        )

        return jobs

    finally:
        connection.close()
