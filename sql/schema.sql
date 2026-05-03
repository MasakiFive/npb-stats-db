CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL,
    stats_date  DATE    NOT NULL,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, stats_date)
);

CREATE TABLE IF NOT EXISTS team_standings (
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
    league        TEXT    NOT NULL CHECK(league IN ('C','P')),
    rank          INTEGER NOT NULL,
    team          TEXT    NOT NULL,
    games         INTEGER,
    wins          INTEGER,
    losses        INTEGER,
    ties          INTEGER,
    win_pct       REAL,
    games_behind  REAL,
    PRIMARY KEY (snapshot_id, league, team)
);

CREATE TABLE IF NOT EXISTS team_batting (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    league               TEXT    NOT NULL CHECK(league IN ('C','P')),
    team                 TEXT    NOT NULL,
    batting_avg          REAL,
    games                INTEGER,
    plate_appearances    INTEGER,
    at_bats              INTEGER,
    runs                 INTEGER,
    hits                 INTEGER,
    doubles              INTEGER,
    triples              INTEGER,
    home_runs            INTEGER,
    total_bases          INTEGER,
    rbi                  INTEGER,
    stolen_bases         INTEGER,
    caught_stealing      INTEGER,
    sacrifice_hits       INTEGER,
    sacrifice_flies      INTEGER,
    walks                INTEGER,
    intentional_walks    INTEGER,
    hit_by_pitch         INTEGER,
    strikeouts           INTEGER,
    grounded_into_dp     INTEGER,
    slugging_pct         REAL,
    on_base_pct          REAL,
    PRIMARY KEY (snapshot_id, league, team)
);

CREATE TABLE IF NOT EXISTS team_pitching (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    league               TEXT    NOT NULL CHECK(league IN ('C','P')),
    team                 TEXT    NOT NULL,
    era                  REAL,
    games                INTEGER,
    wins                 INTEGER,
    losses               INTEGER,
    saves                INTEGER,
    holds                INTEGER,
    hold_points          INTEGER,
    complete_games       INTEGER,
    shutouts             INTEGER,
    no_walks             INTEGER,
    win_pct              REAL,
    batters_faced        INTEGER,
    innings_pitched      REAL,
    hits                 INTEGER,
    home_runs            INTEGER,
    walks                INTEGER,
    intentional_walks    INTEGER,
    hit_by_pitch         INTEGER,
    strikeouts           INTEGER,
    wild_pitches         INTEGER,
    balks                INTEGER,
    runs                 INTEGER,
    earned_runs          INTEGER,
    PRIMARY KEY (snapshot_id, league, team)
);

CREATE TABLE IF NOT EXISTS team_fielding (
    snapshot_id                INTEGER NOT NULL REFERENCES snapshots(id),
    league                     TEXT    NOT NULL CHECK(league IN ('C','P')),
    team                       TEXT    NOT NULL,
    fielding_avg               REAL,
    games                      INTEGER,
    chances                    INTEGER,
    putouts                    INTEGER,
    assists                    INTEGER,
    errors                     INTEGER,
    double_plays_participated  INTEGER,
    double_plays_team          INTEGER,
    passed_balls               INTEGER,
    PRIMARY KEY (snapshot_id, league, team)
);

CREATE TABLE IF NOT EXISTS player_batting (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    league               TEXT    NOT NULL CHECK(league IN ('C','P')),
    player               TEXT    NOT NULL,
    team                 TEXT,
    rank                 INTEGER,
    batting_avg          REAL,
    games                INTEGER,
    plate_appearances    INTEGER,
    at_bats              INTEGER,
    runs                 INTEGER,
    hits                 INTEGER,
    doubles              INTEGER,
    triples              INTEGER,
    home_runs            INTEGER,
    total_bases          INTEGER,
    rbi                  INTEGER,
    stolen_bases         INTEGER,
    caught_stealing      INTEGER,
    sacrifice_hits       INTEGER,
    sacrifice_flies      INTEGER,
    walks                INTEGER,
    intentional_walks    INTEGER,
    hit_by_pitch         INTEGER,
    strikeouts           INTEGER,
    grounded_into_dp     INTEGER,
    slugging_pct         REAL,
    on_base_pct          REAL,
    PRIMARY KEY (snapshot_id, league, player)
);

CREATE TABLE IF NOT EXISTS player_pitching (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    league               TEXT    NOT NULL CHECK(league IN ('C','P')),
    player               TEXT    NOT NULL,
    team                 TEXT,
    rank                 INTEGER,
    era                  REAL,
    games                INTEGER,
    wins                 INTEGER,
    losses               INTEGER,
    saves                INTEGER,
    holds                INTEGER,
    hold_points          INTEGER,
    complete_games       INTEGER,
    shutouts             INTEGER,
    no_walks             INTEGER,
    win_pct              REAL,
    batters_faced        INTEGER,
    innings_pitched      REAL,
    hits                 INTEGER,
    home_runs            INTEGER,
    walks                INTEGER,
    intentional_walks    INTEGER,
    hit_by_pitch         INTEGER,
    strikeouts           INTEGER,
    wild_pitches         INTEGER,
    balks                INTEGER,
    runs                 INTEGER,
    earned_runs          INTEGER,
    PRIMARY KEY (snapshot_id, league, player)
);

CREATE TABLE IF NOT EXISTS season_results (
    year                INTEGER PRIMARY KEY,
    central_champion    TEXT,           -- セ・リーグ優勝
    pacific_champion    TEXT,           -- パ・リーグ優勝
    cs_central_winner   TEXT,           -- CSセ勝者（2007年〜）
    cs_pacific_winner   TEXT,           -- CSパ勝者（2007年〜）
    japan_series_winner TEXT,           -- 日本シリーズ優勝
    notes               TEXT            -- 当時のチーム名・備考
);

CREATE TABLE IF NOT EXISTS player_fielding (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    league               TEXT    NOT NULL CHECK(league IN ('C','P')),
    position             TEXT    NOT NULL,
    player               TEXT    NOT NULL,
    team                 TEXT,
    rank                 INTEGER,
    fielding_avg         REAL,
    games                INTEGER,
    putouts              INTEGER,
    assists              INTEGER,
    errors               INTEGER,
    double_plays         INTEGER,
    passed_balls         INTEGER,
    PRIMARY KEY (snapshot_id, league, position, player)
);

CREATE TABLE IF NOT EXISTS game_batting (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    year         INTEGER NOT NULL,
    game_date    DATE    NOT NULL,
    opponent     TEXT    NOT NULL,
    home_away    TEXT    NOT NULL CHECK(home_away IN ('H','A')),
    row_order    INTEGER NOT NULL,
    position     TEXT,
    player       TEXT    NOT NULL,
    at_bats           INTEGER,
    plate_appearances INTEGER,
    runs              INTEGER,
    hits              INTEGER,
    home_runs         INTEGER,
    rbi               INTEGER,
    stolen_bases      INTEGER,
    walks             INTEGER
);
CREATE INDEX IF NOT EXISTS idx_game_batting_date ON game_batting(game_date);

CREATE TABLE IF NOT EXISTS game_pitching (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    year            INTEGER NOT NULL,
    game_date       DATE    NOT NULL,
    opponent        TEXT    NOT NULL,
    home_away       TEXT    NOT NULL CHECK(home_away IN ('H','A')),
    row_order       INTEGER NOT NULL,
    pitcher         TEXT    NOT NULL,
    result          TEXT,
    innings_pitched REAL,
    batters_faced   INTEGER,
    hits            INTEGER,
    home_runs       INTEGER,
    strikeouts      INTEGER,
    walks           INTEGER,
    hit_by_pitch    INTEGER,
    runs            INTEGER,
    earned_runs     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_game_pitching_date ON game_pitching(game_date);