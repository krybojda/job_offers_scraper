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
| SORTOWANIE
|--------------------------------------------------------------------------
|
| Kolumna i kierunek są pobierane wyłącznie z whitelisty, aby nie dopuścić
| do wstrzyknięcia SQL przez parametr GET.
|--------------------------------------------------------------------------
*/

$sortOptions = [
    'status' => [
        'label' => 'Status',
        'column' => 'is_active',
        'defaultDirection' => 'DESC',
    ],
    'portal' => [
        'label' => 'Portal',
        'column' => 'portal',
        'defaultDirection' => 'ASC',
    ],
    'title' => [
        'label' => 'Stanowisko',
        'column' => 'title',
        'defaultDirection' => 'ASC',
    ],
    'company' => [
        'label' => 'Firma',
        'column' => 'company',
        'defaultDirection' => 'ASC',
    ],
    'location' => [
        'label' => 'Lokalizacja',
        'column' => 'location',
        'defaultDirection' => 'ASC',
    ],
    'work_mode' => [
        'label' => 'Tryb',
        'column' => 'work_mode',
        'defaultDirection' => 'ASC',
    ],
    'work_type' => [
        'label' => 'Typ',
        'column' => 'work_type',
        'defaultDirection' => 'ASC',
    ],
    'experience_level' => [
        'label' => 'Poziom',
        'column' => 'experience_level',
        'defaultDirection' => 'ASC',
    ],
    'contract_type' => [
        'label' => 'Umowa',
        'column' => 'contract_type',
        'defaultDirection' => 'ASC',
    ],
    'salary' => [
        'label' => 'Wynagrodzenie',
        'column' => 'salary',
        'defaultDirection' => 'ASC',
    ],
    'published_at' => [
        'label' => 'Opublikowano',
        'column' => 'published_at',
        'defaultDirection' => 'DESC',
    ],
    'expires_at' => [
        'label' => 'Wygasa',
        'column' => 'expires_at',
        'defaultDirection' => 'ASC',
    ],
    'last_seen_at' => [
        'label' => 'Ostatnio znaleziono',
        'column' => 'last_seen_at',
        'defaultDirection' => 'DESC',
    ],
];

$sort = $_GET['sort'] ?? 'last_seen_at';

if (!isset($sortOptions[$sort])) {
    $sort = 'last_seen_at';
}

$direction = strtoupper($_GET['direction'] ?? '');

if ($direction !== 'ASC' && $direction !== 'DESC') {
    $direction = $sortOptions[$sort]['defaultDirection'];
}

$sortColumn = $sortOptions[$sort]['column'];


/*
|--------------------------------------------------------------------------
| PAGINACJA
|--------------------------------------------------------------------------
*/

$allowedPerPage = [25, 50, 100];

$perPage = (int)($_GET['per_page'] ?? 50);

if (!in_array($perPage, $allowedPerPage, true)) {
    $perPage = 50;
}

$page = max(1, (int)($_GET['page'] ?? 1));


/*
|--------------------------------------------------------------------------
| LICZBA OFERT
|--------------------------------------------------------------------------
*/

$countSql = "
    SELECT COUNT(*) AS total
    FROM jobs
    {$whereSql}
";

$countStmt = $conn->prepare($countSql);

if (!empty($params)) {

    $countStmt->bind_param(
        $types,
        ...$params
    );
}

$countStmt->execute();
$countResult = $countStmt->get_result();
$totalJobs = (int)($countResult->fetch_assoc()['total'] ?? 0);

$totalPages = max(1, (int)ceil($totalJobs / $perPage));

if ($page > $totalPages) {
    $page = $totalPages;
}

offset = ($page - 1) * $perPage;


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
        {$sortColumn} {$direction},
        id DESC
    LIMIT ? OFFSET ?
";

$stmt = $conn->prepare($sql);

$queryTypes = $types . 'ii';
$queryParams = $params;
$queryParams[] = $perPage;
$queryParams[] = $offset;

$stmt->bind_param(
    $queryTypes,
    ...$queryParams
);

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


function queryUrl(array $overrides = []): string
{
    $query = [
        'search' => $_GET['search'] ?? '',
        'portal' => $_GET['portal'] ?? '',
        'active' => $_GET['active'] ?? '',
        'sort' => $_GET['sort'] ?? 'last_seen_at',
        'direction' => $_GET['direction'] ?? 'DESC',
        'per_page' => $_GET['per_page'] ?? 50,
        'page' => $_GET['page'] ?? 1,
    ];

    foreach ($overrides as $key => $value) {
        $query[$key] = $value;
    }

    $query = array_filter(
        $query,
        static fn($value) => $value !== '' && $value !== null
    );

    return '?' . http_build_query($query);
}


function sortUrl(
    string $key,
    array $sortOptions,
    string $currentSort,
    string $currentDirection
): string {
    $nextDirection = 'ASC';

    if ($currentSort === $key && $currentDirection === 'ASC') {
        $nextDirection = 'DESC';
    }

    return queryUrl([
        'sort' => $key,
        'direction' => $nextDirection,
        'page' => 1,
    ]);
}


function sortIndicator(
    string $key,
    string $currentSort,
    string $currentDirection
): string {
    if ($key !== $currentSort) {
        return '';
    }

    return $currentDirection === 'ASC'
        ? ' ↑'
        : ' ↓';
}


function visiblePages(int $currentPage, int $totalPages): array
{
    if ($totalPages <= 7) {
        return range(1, $totalPages);
    }

    $pages = [1];

    $start = max(2, $currentPage - 1);
    $end = min($totalPages - 1, $currentPage + 1);

    if ($start > 2) {
        $pages[] = '...';
    }

    for ($i = $start; $i <= $end; $i++) {
        $pages[] = $i;
    }

    if ($end < $totalPages - 1) {
        $pages[] = '...';
    }

    $pages[] = $totalPages;

    return $pages;
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


    <!-- SORTOWANIE I LICZBA NA STRONĘ -->

    <section class="list-controls">

        <div class="results-info">
            <?php if ($totalJobs > 0): ?>
                Oferty <?= (($page - 1) * $perPage) + 1 ?>–<?= min($page * $perPage, $totalJobs) ?> z <?= $totalJobs ?>
            <?php else: ?>
                Brak ofert
            <?php endif; ?>
        </div>

        <form method="get" class="per-page-form">

            <input type="hidden" name="search" value="<?= e($search) ?>">
            <input type="hidden" name="portal" value="<?= e($portal) ?>">
            <?php if ($activeOnly): ?>
                <input type="hidden" name="active" value="1">
            <?php endif; ?>
            <input type="hidden" name="sort" value="<?= e($sort) ?>">
            <input type="hidden" name="direction" value="<?= e($direction) ?>">
            <input type="hidden" name="page" value="1">

            <label for="per_page">Na stronie:</label>

            <select id="per_page" name="per_page" onchange="this.form.submit()">
                <?php foreach ($allowedPerPage as $value): ?>
                    <option
                        value="<?= $value ?>"
                        <?= $perPage === $value ? 'selected' : '' ?>
                    >
                        <?= $value ?>
                    </option>
                <?php endforeach; ?>
            </select>

        </form>

    </section>


    <!-- TABELA -->

    <section class="table-wrapper">


        <table>


            <thead>

                <tr>

                    <th>
                        <a href="<?= e(sortUrl('status', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Status<?= sortIndicator('status', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('portal', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Portal<?= sortIndicator('portal', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('title', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Stanowisko<?= sortIndicator('title', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('company', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Firma<?= sortIndicator('company', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('location', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Lokalizacja<?= sortIndicator('location', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('work_mode', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Tryb<?= sortIndicator('work_mode', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('work_type', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Typ<?= sortIndicator('work_type', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('experience_level', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Poziom<?= sortIndicator('experience_level', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('contract_type', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Umowa<?= sortIndicator('contract_type', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('salary', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Wynagrodzenie<?= sortIndicator('salary', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('published_at', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Opublikowano<?= sortIndicator('published_at', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('expires_at', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Wygasa<?= sortIndicator('expires_at', $sort, $direction) ?>
                        </a>
                    </th>

                    <th>
                        <a href="<?= e(sortUrl('last_seen_at', $sortOptions, $sort, $direction)) ?>" class="sort-link">
                            Ostatnio znaleziono<?= sortIndicator('last_seen_at', $sort, $direction) ?>
                        </a>
                    </th>

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


    <!-- PAGINACJA -->

    <?php if ($totalPages > 1): ?>

        <nav class="pagination" aria-label="Paginacja ofert">

            <?php if ($page > 1): ?>
                <a
                    href="<?= e(queryUrl(['page' => $page - 1])) ?>"
                    class="page-link"
                    aria-label="Poprzednia strona"
                >
                    ←
                </a>
            <?php else: ?>
                <span class="page-link disabled">←</span>
            <?php endif; ?>


            <?php foreach (visiblePages($page, $totalPages) as $pageItem): ?>

                <?php if ($pageItem === '...'): ?>

                    <span class="page-ellipsis">…</span>

                <?php elseif ((int)$pageItem === $page): ?>

                    <span class="page-link current">
                        <?= (int)$pageItem ?>
                    </span>

                <?php else: ?>

                    <a
                        href="<?= e(queryUrl(['page' => (int)$pageItem])) ?>"
                        class="page-link"
                    >
                        <?= (int)$pageItem ?>
                    </a>

                <?php endif; ?>

            <?php endforeach; ?>


            <?php if ($page < $totalPages): ?>
                <a
                    href="<?= e(queryUrl(['page' => $page + 1])) ?>"
                    class="page-link"
                    aria-label="Następna strona"
                >
                    →
                </a>
            <?php else: ?>
                <span class="page-link disabled">→</span>
            <?php endif; ?>

        </nav>

    <?php endif; ?>


</div>

</body>

</html>