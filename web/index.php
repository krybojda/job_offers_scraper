<?php

$dbHost = getenv('DB_HOST');
$dbPort = (int) getenv('DB_PORT');
$dbName = getenv('DB_NAME');
$dbUser = getenv('DB_USER');
$dbPassword = getenv('DB_PASSWORD');

mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

try {
    $conn = new mysqli($dbHost, $dbUser, $dbPassword, $dbName, $dbPort);
    $conn->set_charset('utf8mb4');
} catch (Exception $e) {
    http_response_code(500);
    die('Błąd połączenia z bazą: ' . htmlspecialchars($e->getMessage(), ENT_QUOTES, 'UTF-8'));
}

function e(?string $value): string
{
    return htmlspecialchars($value ?? '', ENT_QUOTES, 'UTF-8');
}

function formatDate(?string $date): string
{
    if (!$date) {
        return '-';
    }

    $timestamp = strtotime($date);

    return $timestamp === false ? e($date) : date('d.m.Y H:i', $timestamp);
}

function formatValue(?string $value): string
{
    return $value ? e($value) : '-';
}

$portal = trim($_GET['portal'] ?? '');
$search = trim($_GET['search'] ?? '');
$activeOnly = ($_GET['active'] ?? '') === '1';

$where = [];
$params = [];
$types = '';

if ($portal !== '') {
    $where[] = 'portal = ?';
    $params[] = $portal;
    $types .= 's';
}

if ($search !== '') {
    $where[] = '(title LIKE ? OR company LIKE ? OR location LIKE ? OR tech_stack LIKE ?)';
    $value = '%' . $search . '%';

    for ($i = 0; $i < 4; $i++) {
        $params[] = $value;
    }

    $types .= 'ssss';
}

if ($activeOnly) {
    $where[] = 'is_active = 1';
}

$whereSql = $where ? 'WHERE ' . implode(' AND ', $where) : '';

$sortOptions = [
    'status' => ['is_active', 'Status', 'DESC'],
    'portal' => ['portal', 'Portal', 'ASC'],
    'title' => ['title', 'Stanowisko', 'ASC'],
    'company' => ['company', 'Firma', 'ASC'],
    'location' => ['location', 'Lokalizacja', 'ASC'],
    'work_mode' => ['work_mode', 'Tryb', 'ASC'],
    'work_type' => ['work_type', 'Typ', 'ASC'],
    'experience_level' => ['experience_level', 'Poziom', 'ASC'],
    'contract_type' => ['contract_type', 'Umowa', 'ASC'],
    'salary' => ['salary', 'Wynagrodzenie', 'ASC'],
    'published_at' => ['published_at', 'Opublikowano', 'DESC'],
    'expires_at' => ['expires_at', 'Wygasa', 'ASC'],
    'last_seen_at' => ['last_seen_at', 'Ostatnio znaleziono', 'DESC'],
];

$sort = $_GET['sort'] ?? 'last_seen_at';
if (!isset($sortOptions[$sort])) {
    $sort = 'last_seen_at';
}

$direction = strtoupper($_GET['direction'] ?? '');
if (!in_array($direction, ['ASC', 'DESC'], true)) {
    $direction = $sortOptions[$sort][2];
}

$sortColumn = $sortOptions[$sort][0];
$allowedPerPage = [25, 50, 100];
$perPage = (int) ($_GET['per_page'] ?? 50);

if (!in_array($perPage, $allowedPerPage, true)) {
    $perPage = 50;
}

$page = max(1, (int) ($_GET['page'] ?? 1));

$countStmt = $conn->prepare("SELECT COUNT(*) total FROM jobs {$whereSql}");
if ($params) {
    $countStmt->bind_param($types, ...$params);
}

$countStmt->execute();
$totalJobs = (int) ($countStmt->get_result()->fetch_assoc()['total'] ?? 0);
$totalPages = max(1, (int) ceil($totalJobs / $perPage));

if ($page > $totalPages) {
    $page = $totalPages;
}

$offset = ($page - 1) * $perPage;
$sql = "SELECT id, portal, title, company, location, work_mode, work_type, experience_level,
               contract_type, salary, url, keyword, published_at, first_seen_at, last_seen_at,
               is_active, missed_count, expires_text, expires_at, details_scraped_at
        FROM jobs {$whereSql}
        ORDER BY {$sortColumn} {$direction}, id DESC
        LIMIT ? OFFSET ?";
$stmt = $conn->prepare($sql);
$queryTypes = $types . 'ii';
$queryParams = $params;
$queryParams[] = $perPage;
$queryParams[] = $offset;
$stmt->bind_param($queryTypes, ...$queryParams);
$stmt->execute();
$jobs = $stmt->get_result()->fetch_all(MYSQLI_ASSOC);

$stats = $conn->query(
    'SELECT
        COUNT(*) total,
        COALESCE(SUM(is_active = 1), 0) active,
        COALESCE(SUM(first_seen_at >= NOW() - INTERVAL 24 HOUR), 0) new_24h
    FROM jobs'
)->fetch_assoc();

$portals = $conn->query(
    "SELECT DISTINCT portal
     FROM jobs
     WHERE portal IS NOT NULL AND portal <> ''
     ORDER BY portal"
)->fetch_all(MYSQLI_ASSOC);

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

    $query = array_filter($query, fn ($value) => $value !== '' && $value !== null);

    return '?' . http_build_query($query);
}

function sortUrl(string $key, string $current, string $direction): string
{
    $nextDirection = ($current === $key && $direction === 'ASC') ? 'DESC' : 'ASC';

    return queryUrl([
        'sort' => $key,
        'direction' => $nextDirection,
        'page' => 1,
    ]);
}

function indicator(string $key, string $current, string $direction): string
{
    if ($key !== $current) {
        return '';
    }

    return $direction === 'ASC' ? ' ↑' : ' ↓';
}

function pageItems(int $page, int $total): array
{
    if ($total <= 7) {
        return range(1, $total);
    }

    $items = [1];
    $start = max(2, $page - 1);
    $end = min($total - 1, $page + 1);

    if ($start > 2) {
        $items[] = '...';
    }

    for ($item = $start; $item <= $end; $item++) {
        $items[] = $item;
    }

    if ($end < $total - 1) {
        $items[] = '...';
    }

    $items[] = $total;

    return $items;
}
?>
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Oferty pracy</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <header class="header">
            <div>
                <h1>Oferty pracy</h1>
                <p>Agregator ofert pracy</p>
            </div>
        </header>

        <section class="stats">
            <div class="stat-card">
                <span>Wszystkie</span>
                <strong><?= (int) ($stats['total'] ?? 0) ?></strong>
            </div>
            <div class="stat-card">
                <span>Aktywne</span>
                <strong><?= (int) ($stats['active'] ?? 0) ?></strong>
            </div>
            <div class="stat-card">
                <span>Nowe 24h</span>
                <strong><?= (int) ($stats['new_24h'] ?? 0) ?></strong>
            </div>
        </section>

        <section class="filters">
            <form method="get">
                <input
                    type="text"
                    name="search"
                    placeholder="Szukaj stanowiska, firmy, lokalizacji lub technologii..."
                    value="<?= e($search) ?>"
                >
                <select name="portal">
                    <option value="">Wszystkie portale</option>
                    <?php foreach ($portals as $item): ?>
                        <option value="<?= e($item['portal']) ?>" <?= $portal === $item['portal'] ? 'selected' : '' ?>>
                            <?= e($item['portal']) ?>
                        </option>
                    <?php endforeach; ?>
                </select>
                <label class="checkbox">
                    <input type="checkbox" name="active" value="1" <?= $activeOnly ? 'checked' : '' ?>>
                    Tylko aktywne
                </label>
                <button type="submit">Szukaj</button>
                <a href="index.php" class="reset">Wyczyść</a>
            </form>
        </section>

        <section class="list-controls">
            <div class="results-info">
                <?php if ($totalJobs): ?>
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
                    <?php foreach ($allowedPerPage as $number): ?>
                        <option value="<?= $number ?>" <?= $perPage === $number ? 'selected' : '' ?>>
                            <?= $number ?>
                        </option>
                    <?php endforeach; ?>
                </select>
            </form>
        </section>

        <section class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <?php foreach ($sortOptions as $key => $option): ?>
                            <th>
                                <a class="sort-link" href="<?= e(sortUrl($key, $sort, $direction)) ?>">
                                    <?= $option[1] . indicator($key, $sort, $direction) ?>
                                </a>
                            </th>
                        <?php endforeach; ?>
                    </tr>
                </thead>
                <tbody>
                    <?php if (!$jobs): ?>
                        <tr>
                            <td colspan="13" class="empty">Brak ofert.</td>
                        </tr>
                    <?php else: ?>
                        <?php foreach ($jobs as $job): ?>
                            <?php $isNewOffer = !empty($job['first_seen_at']) && strtotime($job['first_seen_at']) >= time() - 86400; ?>
                            <tr class="<?= $isNewOffer ? 'new-offer' : '' ?>">
                                <td>
                                    <?php if ((int) $job['is_active'] === 1): ?>
                                        <span class="status active">● Aktywna</span>
                                    <?php else: ?>
                                        <span class="status inactive">● Nieaktywna</span>
                                    <?php endif; ?>
                                </td>
                                <td><span class="portal"><?= e($job['portal']) ?></span></td>
                                <td>
                                    <a
                                        href="<?= e($job['url']) ?>"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="job-title"
                                        title="Otwórz ofertę"
                                    >
                                        <?= e($job['title']) ?>
                                    </a>
                                    <?php if ($job['keyword']): ?>
                                        <div class="keyword"><?= e($job['keyword']) ?></div>
                                    <?php endif; ?>
                                </td>
                                <td><?= formatValue($job['company']) ?></td>
                                <td><?= formatValue($job['location']) ?></td>
                                <td><?= formatValue($job['work_mode']) ?></td>
                                <td><?= formatValue($job['work_type']) ?></td>
                                <td><?= formatValue($job['experience_level']) ?></td>
                                <td><?= formatValue($job['contract_type']) ?></td>
                                <td><?= formatValue($job['salary']) ?></td>
                                <td><?= formatDate($job['published_at']) ?></td>
                                <td>
                                    <?php if ($job['expires_at']): ?>
                                        <?= formatDate($job['expires_at']) ?>
                                    <?php elseif ($job['expires_text']): ?>
                                        <?= e($job['expires_text']) ?>
                                    <?php else: ?>
                                        -
                                    <?php endif; ?>
                                </td>
                                <td><?= formatDate($job['last_seen_at']) ?></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </tbody>
            </table>
        </section>

        <?php if ($totalPages > 1): ?>
            <nav class="pagination" aria-label="Paginacja ofert">
                <?php if ($page > 1): ?>
                    <a class="page-link" href="<?= e(queryUrl(['page' => $page - 1])) ?>">←</a>
                <?php else: ?>
                    <span class="page-link disabled">←</span>
                <?php endif; ?>

                <?php foreach (pageItems($page, $totalPages) as $item): ?>
                    <?php if ($item === '...'): ?>
                        <span class="page-ellipsis">…</span>
                    <?php elseif ((int) $item === $page): ?>
                        <span class="page-link current"><?= $item ?></span>
                    <?php else: ?>
                        <a class="page-link" href="<?= e(queryUrl(['page' => (int) $item])) ?>">
                            <?= $item ?>
                        </a>
                    <?php endif; ?>
                <?php endforeach; ?>

                <?php if ($page < $totalPages): ?>
                    <a class="page-link" href="<?= e(queryUrl(['page' => $page + 1])) ?>">→</a>
                <?php else: ?>
                    <span class="page-link disabled">→</span>
                <?php endif; ?>
            </nav>
        <?php endif; ?>
    </div>
</body>
</html>
