import os
import time

import mysql.connector
from mysql.connector import Error


def get_db_connection():
    """
    Tworzy po??czenie z MySQL.
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
    Czeka na dost?pno?? MySQL.
    """

    for attempt in range(1, max_attempts + 1):

        try:
            connection = get_db_connection()

            if connection.is_connected():
                connection.close()

                print("Po??czenie z MySQL: OK")

                return True

        except Error as error:

            print(
                f"MySQL niedost?pny "
                f"(pr?ba {attempt}/{max_attempts}): "
                f"{error}"
            )

            if attempt < max_attempts:
                time.sleep(delay)

        except Exception as error:
            print(
                f"Oczekiwanie na MySQL "
                f"(pr?ba {attempt}/{max_attempts}): "
                f"{error}"
            )
            if attempt < max_attempts:
                time.sleep(delay)

    return False


def save_job(job):
    """
    Dodaje now? ofert? albo aktualizuje istniej?c?.

    Szczeg??y nigdy nie s? kasowane podczas aktualizacji.
    S?owa kluczowe (keyword) s? ??czone bez duplikowania.
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
                %s,
                %s,
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
                company = COALESCE(VALUES(company), company),
                location = COALESCE(VALUES(location), location),
                work_mode = COALESCE(VALUES(work_mode), work_mode),
                work_type = COALESCE(VALUES(work_type), work_type),
                experience_level = COALESCE(VALUES(experience_level), experience_level),
                contract_type = COALESCE(VALUES(contract_type), contract_type),
                salary = COALESCE(VALUES(salary), salary),
                url = VALUES(url),
                keyword = CASE
                    WHEN keyword IS NULL OR keyword = '' THEN VALUES(keyword)
                    WHEN VALUES(keyword) IS NULL OR VALUES(keyword) = '' THEN keyword
                    WHEN FIND_IN_SET(VALUES(keyword), REPLACE(keyword, ', ', ',')) > 0 THEN keyword
                    ELSE CONCAT(keyword, ', ', VALUES(keyword))
                END,
                published_at = COALESCE(VALUES(published_at), published_at),
                last_seen_at = NOW(),
                is_active = 1,
                missed_count = 0
        """

        values = (
            job["portal"],
            job["source_id"],
            job["title"],
            job.get("company"),
            job.get("location"),
            job.get("work_mode"),
            job.get("work_type"),
            job.get("experience_level"),
            job.get("contract_type"),
            job.get("salary"),
            job["url"],
            job.get("keyword"),
            job.get("published_at"),
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
    Zapisuje szczeg??owe informacje o ofercie.

    details_scraped_at jest ustawiane TYLKO wtedy,
    gdy strona szczeg??owa zosta?a poprawnie odczytana
    i otrzymali?my wynik details.
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
                details_scraped_at = NOW(),
                details_complete = %s
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
            int(
                bool(details.get("job_description"))
                and bool(details.get("tech_stack"))
            ),
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
            f"[SZCZEG??Y] zapisano: {source_id}"
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
    kt?rych nie znaleziono w pe?nym przebiegu.

    Funkcja powinna by? wywo?ywana tylko wtedy,
    gdy ca?y skan danego portalu zako?czy? si? poprawnie.
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
            "[AKTYWNO??] "
            f"zaktualizowano portal: {portal}"
        )

    finally:

        connection.close()


def get_jobs_without_details(
    portal,
    limit=20,
    retry_after_seconds=21600,
):
    """
    Pobiera aktywne oferty wymagaj?ce pobrania lub ponownego
    pobrania szczeg???w.
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
              AND is_active = 1
              AND (
                    details_scraped_at IS NULL
                    OR (
                        details_complete = 0
                        AND details_scraped_at <= DATE_SUB(
                            NOW(), INTERVAL %s SECOND
                        )
                    )
              )
            ORDER BY id ASC
            LIMIT %s
            """,
            (
                portal,
                int(retry_after_seconds),
                int(limit),
            ),
        )

        jobs = cursor.fetchall()

        print(
            f"[SZCZEG??Y] DB zwr?ci?a: "
            f"{len(jobs)} ofert bez szczeg???w "
            f"dla portalu {portal}"
        )

        return jobs

    finally:
        connection.close()


def cleanup_ignored_jobs(ignored_keywords):
    """
    Dezaktywuje w bazie danych aktywne oferty pasuj?ce do ignorowanych s??w kluczowych.
    Pozwala to natychmiast ukry? oferty (np. Senior), kt?re zosta?y dodane do bazy
    przed modyfikacj? ignored_keywords.txt.
    """
    if not ignored_keywords:
        return 0

    from filters import is_ignored_job

    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, portal, source_id, title, experience_level
            FROM jobs
            WHERE is_active = 1
            """
        )
        active_jobs = cursor.fetchall()

        to_deactivate = [
            job["id"]
            for job in active_jobs
            if is_ignored_job(job, ignored_keywords)
        ]

        if to_deactivate:
            placeholders = ",".join(["%s"] * len(to_deactivate))
            cursor.execute(
                f"""
                UPDATE jobs
                SET is_active = 0
                WHERE id IN ({placeholders})
                """,
                to_deactivate,
            )
            connection.commit()
            print(
                f"[FILTR] Dezaktywowano {len(to_deactivate)} ofert "
                f"w bazie pasuj?cych do ignorowanych s??w kluczowych."
            )

        return len(to_deactivate)

    finally:
        connection.close()


def deduplicate_existing_jobs():
    """
    Dezaktywuje duplikaty ofert w bazie danych (np. ta sama firma, tytu? i portal),
    pozostawiaj?c najnowszy aktywny rekord.
    """
    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT portal, LOWER(TRIM(title)) as norm_title, LOWER(TRIM(company)) as norm_company,
                   title as orig_title, company as orig_company,
                   COUNT(*) as count, MAX(id) as keep_id
            FROM jobs
            WHERE is_active = 1
              AND company IS NOT NULL
              AND company != ''
              AND title IS NOT NULL
              AND title != ''
            GROUP BY portal, norm_title, norm_company
            HAVING count > 1
            """
        )
        duplicate_groups = cursor.fetchall()

        total_deactivated = 0
        for group in duplicate_groups:
            cursor.execute(
                """
                UPDATE jobs
                SET is_active = 0
                WHERE portal = %s
                  AND LOWER(TRIM(title)) = %s
                  AND LOWER(TRIM(company)) = %s
                  AND is_active = 1
                  AND id != %s
                """,
                (
                    group["portal"],
                    group["norm_title"],
                    group["norm_company"],
                    group["keep_id"],
                ),
            )
            total_deactivated += cursor.rowcount

        if total_deactivated > 0:
            connection.commit()
            print(
                f"[DEDUPLIKACJA] Dezaktywowano {total_deactivated} "
                "zduplikowanych ofert w bazie."
            )

        return total_deactivated

    finally:
        connection.close()
