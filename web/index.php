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
        htmlspecialchars($e->getMessage(), ENT_QUOTES, 'UTF-8')
    );
}

$portal = trim($_GET['portal'] ?? '');
$search = trim($_GET['search'] ?? '');
$activeOnly = isset($_GET['active']) && $_GET['active'] === '1';

$where = [];
$params = [];
$types = '';

if ($portal !== '') {
    $where[] = 'portal = ?';
    $params[] = $portal;
    $types .= 's';
}

if ($search !== '') {
    $where[] = '(title LIKE ? OR company LIKE ? OR location LIKE ?)';
    $searchValue = '%' . $search . '%';

    $params[] = $searchValue;
    $params[] = $searchValue;
    $params[] = $searchValue;

    $types .= 'sss';
}

if ($activeOnly) {
    $where[] = 'is_active = 1';
}

$whereSql = '';

if (!empty($where)) {
    $whereSql = 'WHERE ' . implode(' AND ', $where);
}

$sql = "
    SELECT
        id,
        portal,
        title,
        company,
        location,
        salary,
        url,
        published_at,
        first_seen_at,
        last_seen_at,
        is_active
    FROM jobs
    {$whereSql}
    ORDER BY last_seen_at DESC
";

$stmt = $conn->prepare($sql);

if (!empty($params)) {
    $stmt->bind_param($types, ...$params);
}

$stmt->execute();

$result = $stmt->get_result();

$jobs = $result->fetch_all(MYSQLI_ASSOC);

$statsResult = $conn->query("
    SELECT
        COUNT(*) AS total,
        SUM(is_active = 1) AS active,
        SUM(first_seen_at >= NOW() - INTERVAL 24 HOUR) AS new_24h
    FROM jobs
");

$stats = $statsResult->fetch_assoc();

$portalsResult = $conn->query("
    SELECT DISTINCT portal
    FROM jobs
    WHERE portal IS NOT NULL AND portal <> ''
    ORDER BY portal
");

$portals = $portalsResult->fetch_all(MYSQLI_ASSOC);

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

    return date('d.m.Y H:i', $timestamp);
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
            <strong><?= (int)($stats['total'] ?? 0) ?></strong>
        </div>

        <div class="stat-card">
            <span>Aktywne</span>
            <strong><?= (int)($stats['active'] ?? 0) ?></strong>
        </div>

        <div class="stat-card">
            <span>Nowe 24h</span>
            <strong><?= (int)($stats['new_24h'] ?? 0) ?></strong>
        </div>

    </section>

    <section class="filters">

        <form method="get">

            <input
                type="text"
                name="search"
                placeholder="Szukaj stanowiska, firmy lub lokalizacji..."
                value="<?= e($search) ?>"
            >

            <select name="portal">
                <option value="">Wszystkie portale</option>

                <?php foreach ($portals as $item): ?>
                    <option
                        value="<?= e($item['portal']) ?>"
                        <?= $portal === $item['portal'] ? 'selected' : '' ?>
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
                    <?= $activeOnly ? 'checked' : '' ?>
                >
                Tylko aktywne
            </label>

            <button type="submit">
                Szukaj
            </button>

            <a href="index.php" class="reset">
                Wyczyść
            </a>

        </form>

    </section>

    <section class="table-wrapper">

        <table>

            <thead>
                <tr>
                    <th>Status</th>
                    <th>Portal</th>
                    <th>Stanowisko</th>
                    <th>Firma</th>
                    <th>Lokalizacja</th>
                    <th>Wynagrodzenie</th>
                    <th>Opublikowano</th>
                    <th>Ostatnio znaleziono</th>
                </tr>
            </thead>

            <tbody>

            <?php if (empty($jobs)): ?>

                <tr>
                    <td colspan="8" class="empty">
                        Brak ofert.
                    </td>
                </tr>

            <?php else: ?>

                <?php foreach ($jobs as $job): ?>

                    <tr>

                        <td>
                            <?php if ((int)$job['is_active'] === 1): ?>
                                <span class="status active">
                                    ● Aktywna
                                </span>
                            <?php else: ?>
                                <span class="status inactive">
                                    ● Nieaktywna
                                </span>
                            <?php endif; ?>
                        </td>

                        <td>
                            <span class="portal">
                                <?= e($job['portal']) ?>
                            </span>
                        </td>

                        <td>
                            <a
                                href="<?= e($job['url']) ?>"
                                target="_blank"
                                rel="noopener noreferrer"
                                class="job-title"
                            >
                                <?= e($job['title']) ?>
                            </a>
                        </td>

                        <td>
                            <?= e($job['company']) ?>
                        </td>

                        <td>
                            <?= e($job['location']) ?>
                        </td>

                        <td>
                            <?= e($job['salary']) ?: '-' ?>
                        </td>

                        <td>
                            <?= formatDate($job['published_at']) ?>
                        </td>

                        <td>
                            <?= formatDate($job['last_seen_at']) ?>
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