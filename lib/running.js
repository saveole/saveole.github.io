const fs = require('fs');
const path = require('path');

function formatDuration(seconds) {
    return Math.round(seconds / 60) + 'min';
}

function formatPace(secondsPerKm) {
    const min = Math.floor(secondsPerKm / 60);
    const sec = secondsPerKm % 60;
    return min + "'" + (sec < 10 ? '0' : '') + sec + '"';
}

function loadRunningMap(dir) {
    const runningMap = {};
    const file = path.join(dir, 'activities.json');
    if (fs.existsSync(file)) {
        JSON.parse(fs.readFileSync(file, 'utf-8')).forEach(a => {
            runningMap[a.date] = a.distance_km;
        });
    }
    return runningMap;
}

function mergeRunningMap(tokenDays, runningMap) {
    const existingDates = new Set(tokenDays.map(d => d.date));
    tokenDays.forEach(d => { d.running_km = runningMap[d.date] || 0; });
    Object.keys(runningMap).forEach(date => {
        if (!existingDates.has(date)) {
            tokenDays.push({
                date,
                total_tokens: { input: 0, output: 0, cache_read: 0, cache_creation: 0 },
                running_km: runningMap[date]
            });
        }
    });
    tokenDays.sort((a, b) => a.date.localeCompare(b.date));
    return tokenDays;
}

function buildRunningPageData(dir) {
    if (!fs.existsSync(dir)) return null;

    const activitiesRaw = JSON.parse(fs.readFileSync(path.join(dir, 'activities.json'), 'utf-8'));
    const bodyRaw = JSON.parse(fs.readFileSync(path.join(dir, 'body.json'), 'utf-8'));

    const dateSet = new Set();
    activitiesRaw.forEach(a => dateSet.add(a.date));
    bodyRaw.forEach(b => dateSet.add(b.date));
    const timeline = Array.from(dateSet).sort();

    const activities = activitiesRaw.map(a => ({
        date: a.date,
        start_time: a.start_time || '',
        type: a.type || 'running',
        distance_km: a.distance_km,
        duration: formatDuration(a.duration_s),
        pace: formatPace(a.avg_pace_s_per_km),
        avg_hr: a.avg_hr,
        max_hr: a.max_hr,
        cadence_spm: a.cadence_spm
    })).sort((a, b) => b.date.localeCompare(a.date));

    const tracks = activitiesRaw
        .filter(a => a.summary_polyline && a.distance_km >= 5)
        .map(a => ({
            date: a.date,
            distance_km: a.distance_km,
            pace: formatPace(a.avg_pace_s_per_km),
            duration: formatDuration(a.duration_s),
            summary_polyline: a.summary_polyline
        }))
        .sort((a, b) => b.date.localeCompare(a.date));

    return {
        timelineJSON: JSON.stringify(timeline),
        bodyJSON: JSON.stringify(bodyRaw),
        activitiesJSON: JSON.stringify(activities),
        tracksJSON: JSON.stringify(tracks)
    };
}

module.exports = { loadRunningMap, mergeRunningMap, buildRunningPageData };