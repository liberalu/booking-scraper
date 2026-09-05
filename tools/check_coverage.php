<?php

declare(strict_types=1);

$path = $argv[1] ?? '';
$minimum = isset($argv[2]) ? (float) $argv[2] : 50.0;
if ($path === '' || ! is_file($path)) {
    fwrite(STDERR, "Coverage report not found\n");
    exit(1);
}

$xml = simplexml_load_file($path);
$metrics = $xml?->project->metrics;
if ($metrics === null) {
    fwrite(STDERR, "Coverage metrics not found\n");
    exit(1);
}

$statements = (int) $metrics['statements'];
$covered = (int) $metrics['coveredstatements'];
$percentage = $statements === 0 ? 0.0 : ($covered / $statements) * 100;
printf("Line coverage: %.2f%% (minimum %.2f%%)\n", $percentage, $minimum);
exit($percentage >= $minimum ? 0 : 1);
