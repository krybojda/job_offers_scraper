<?php

$dbHost = getenv('DB_HOST');
$dbPort = (int) getenv('DB_PORT');
$dbName = getenv('DB_NAME');
$dbUser = getenv('DB_USER');
$dbPassword = getenv('DB_PASSWORD');

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

try {
    $conn = new mysqli(
        $dbHost,
        $dbUser,
        $dbPassword,
        $dbName,
        $dbPort
    );

    $conn->set_charset('utf8mb4');

} catch (Exception $e) {
    http_response_code(500);

    die(
        'Błąd połączenia z bazą: ' .
        htmlspecialchars(
            $e->getMessage(),
            ENT_QUOTES,
            'UTF-8'
        )
    );
}


/*
|--------------------------------------------------------------------------
| FILTRY
|--------------------------------------------------------------------------
*/

$portal = trim($_GET['portal'] ?? '');
$search = trim($_GET['search'] ?? '');
$activeOnly = isset($_GET['active'])
    && $_GET['active'] === '1';


$where = [];
$params = [];
$types = '';


if ($portal !== '') {
    $where[] = 'portal = ?';
    $params[] = $portal;
    $types .= 's';
}


if ($search !== '') {

    $where[] = '
        (
            title LIKE ?
            OR company LIKE ?
            OR location LIKE ?
            OR tech_stack LIKE ?
        )
    ';

    $searchValue = '%' . $search . '%';

    $params[] = $searchValue;
    $params[] = $searchValue;
    $params[] = $searchValue;
    $params[] = $searchValue;

    $types .= 'ssss';
}


if ($activeOnly) {
    $where[] = 'is_active = 1';
}


$whereSql = '';

if (!empty($where)) {
    $whereSql = 'WHERE ' . implode(
        ' AND ',
        $where
    );
}


/*
|--------------------------------------------------------------------------
| OFERTY
|--------------------------------------------------------------------------
*/

$sql = "
    SELECT
        id,
        portal,
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
        missed_count,
        expires_text,
        expires_at,
        details_scraped_at
    FROM jobs
    {$whereSql}
    ORDER BY
        is_active DESC,
        last_seen_at DESC
";


$stmt = $conn->prepare($sql);


if (!empty($params)) {

    $stmt->bind_param(
        $types,
        ...$params
    );
}


$stmt->execute();

$result = $stmt->get_result();

$jobs = $result->fetch_all(
    MYSQLI_ASSOC
);


/*
|--------------------------------------------------------------------------
| STATYSTYKI
|--------------------------------------------------------------------------
*/

$statsResult = $conn->query("
    SELECT
        COUNT(*) AS total,

        COALESCE(
            SUM(is_active = 1),
            0
        ) AS active,

        COALESCE(
            SUM(
                first_seen_at >=
                NOW() - INTERVAL 24 HOUR
            ),
            0
        ) AS new_24h

    FROM jobs
");


$stats = $statsResult->fetch_assoc();


/*
|--------------------------------------------------------------------------
| PORTALE
|--------------------------------------------------------------------------
*/

$portalsResult = $conn->query("
    SELECT DISTINCT portal
    FROM jobs
    WHERE portal IS NOT NULL
      AND portal <> ''
    ORDER BY portal
");


$portals = $portalsResult->fetch_all(
    MYSQLI_ASSOC
);


/*
|--------------------------------------------------------------------------
| FUNKCJE
|--------------------------------------------------------------------------
*/

function e(?string $value): string
{
    return htmlspecialchars(
        $value ?? '',
        ENT_QUOTES,
        'UTF-8'
    );
}


function formatDate(?string $date): string
{
    if (!$date) {
        return '-';
    }

    $timestamp = strtotime($date);

    if ($timestamp === false) {
        return e($date);
    }

    return date(
        'd.m.Y H:i',
        $timestamp
    );
}


function formatValue(?string $value): string
{
    return $value
        ? e($value)
        : '-';
}

?>

<!DOCTYPE html>

<html lang="pl">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>Oferty pracy</title>

    <link
        rel="stylesheet"
        href="style.css"
    >

</head>


<body>

<div class="container">


    <!-- HEADER -->

    <header class="header">

        <div>

            <h1>Oferty pracy</h1>

            <p>
                Agregator ofert pracy
            </p>

        </div>

    </header>


    <!-- STATYSTYKI -->

    <section class="stats">


        <div class="stat-card">

            <span>
                Wszystkie
            </span>

            <strong>
                <?= (int)($stats['total'] ?? 0) ?>
            </strong>

        </div>


        <div class="stat-card">

            <span>
                Aktywne
            </span>

            <strong>
                <?= (int)($stats['active'] ?? 0) ?>
            </strong>

        </div>


        <div class="stat-card">

            <span>
                Nowe 24h
            </span>

            <strong>
                <?= (int)($stats['new_24h'] ?? 0) ?>
            </strong>

        </div>


    </section>


    <!-- FILTRY -->

    <section class="filters">

        <form method="get">


            <input
                type="text"
                name="search"
                placeholder="Szukaj stanowiska, firmy, lokalizacji lub technologii..."
                value="<?= e($search) ?>"
            >


            <select name="portal">

                <option value="">
                    Wszystkie portale
                </option>


                <?php foreach ($portals as $item): ?>

                    <option
                        value="<?= e($item['portal']) ?>"
                        <?= $portal === $item['portal']
                            ? 'selected'
                            : ''
                        ?>
                    >

                        <?= e($item['portal']) ?>

                    </option>

                <?php endforeach; ?>

            </select>


            <label class="checkbox">

                <input
                    type="checkbox"
                    name="active"
                    value="1"
                    <?= $activeOnly
                        ? 'checked'
                        : ''
                    ?>
                >

                Tylko aktywne

            </label>


            <button type="submit">
                Szukaj
            </button>


            <a
                href="index.php"
                class="reset"
            >
                Wyczyść
            </a>


        </form>

    </section>


    <!-- TABELA -->

    <section class="table-wrapper">


        <table>


            <thead>

                <tr>

                    <th>Status</th>

                    <th>Portal</th>

                    <th>Stanowisko</th>

                    <th>Firma</th>

                    <th>Lokalizacja</th>

                    <th>Tryb</th>

                    <th>Typ</th>

                    <th>Poziom</th>

                    <th>Umowa</th>

                    <th>Wynagrodzenie</th>

                    <th>Opublikowano</th>

                    <th>Wygasa</th>

                    <th>Ostatnio znaleziono</th>

                </tr>

            </thead>


            <tbody>


            <?php if (empty($jobs)): ?>


                <tr>

                    <td
                        colspan="13"
                        class="empty"
                    >
                        Brak ofert.
                    </td>

                </tr>


            <?php else: ?>


                <?php foreach ($jobs as $job): ?>


                    <tr>


                        <!-- STATUS -->

                        <td>

                            <?php if (
                                (int)$job['is_active'] === 1
                            ): ?>

                                <span class="status active">
                                    ● Aktywna
                                </span>

                            <?php else: ?>

                                <span class="status inactive">
                                    ● Nieaktywna
                                </span>

                            <?php endif; ?>


                        </td>


                        <!-- PORTAL -->

                        <td>

                            <span class="portal">

                                <?= e(
                                    $job['portal']
                                ) ?>

                            </span>

                        </td>


                        <!-- STANOWISKO -->

                        <td>

                            <a
                                href="<?= e(
                                    $job['url']
                                ) ?>"
                                target="_blank"
                                rel="noopener noreferrer"
                                class="job-title"
                                title="Otwórz ofertę"
                            >

                                <?= e(
                                    $job['title']
                                ) ?>

                            </a>


                            <?php if (
                                $job['keyword']
                            ): ?>

                                <div class="keyword">

                                    <?= e(
                                        $job['keyword']
                                    ) ?>

                                </div>

                            <?php endif; ?>


                        </td>


                        <!-- FIRMA -->

                        <td>

                            <?= formatValue(
                                $job['company']
                            ) ?>

                        </td>


                        <!-- LOKALIZACJA -->

                        <td>

                            <?= formatValue(
                                $job['location']
                            ) ?>

                        </td>


                        <!-- TRYB -->

                        <td>

                            <?= formatValue(
                                $job['work_mode']
                            ) ?>

                        </td>


                        <!-- TYP -->

                        <td>

                            <?= formatValue(
                                $job['work_type']
                            ) ?>

                        </td>


                        <!-- POZIOM -->

                        <td>

                            <?= formatValue(
                                $job['experience_level']
                            ) ?>

                        </td>


                        <!-- UMOWA -->

                        <td>

                            <?= formatValue(
                                $job['contract_type']
                            ) ?>

                        </td>


                        <!-- WYNAGRODZENIE -->

                        <td>

                            <?= formatValue(
                                $job['salary']
                            ) ?>

                        </td>


                        <!-- OPUBLIKOWANO -->

                        <td>

                            <?= formatDate(
                                $job['published_at']
                            ) ?>

                        </td>


                        <!-- WYGASA -->

                        <td>

                            <?php if (
                                $job['expires_at']
                            ): ?>

                                <?= formatDate(
                                    $job['expires_at']
                                ) ?>

                            <?php elseif (
                                $job['expires_text']
                            ): ?>

                                <?= e(
                                    $job['expires_text']
                                ) ?>

                            <?php else: ?>

                                -

                            <?php endif; ?>

                        </td>


                        <!-- OSTATNIO ZNALEZIONO -->

                        <td>

                            <?= formatDate(
                                $job['last_seen_at']
                            ) ?>

                        </td>


                    </tr>


                <?php endforeach; ?>


            <?php endif; ?>


            </tbody>


        </table>


    </section>


</div>

</body>

</html>