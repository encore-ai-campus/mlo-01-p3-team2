CREATE TABLE IF NOT EXISTS `account_activity_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `event_type` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `end_reason` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chat_activity_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `message_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `floor_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `post_activity_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `post_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `action` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `revision` BIGINT NOT NULL,
  `zone_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `comment_activity_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `comment_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `post_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parent_comment_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `action` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `revision` BIGINT NOT NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `content_activity_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `content_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `category_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `domain` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `content_kind` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `action` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `zone_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `quiz_attempt_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `attempt_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `question_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `content_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `choice_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `is_correct` BOOLEAN NOT NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `movement_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `floor_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `zone_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `x` DOUBLE NOT NULL,
  `y` DOUBLE NOT NULL,
  `input_kind` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `floor_transfer_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `from_floor_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `to_floor_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `zone_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `point_grant_fact` (
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `occurred_at` DATETIME(6) NOT NULL,
  `user_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `class_group_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `session_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `ledger_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `attempt_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `delta` BIGINT NOT NULL,
  `balance_after` BIGINT NOT NULL,
  `parser_version` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `parser_rank` INT NOT NULL,
  `std_fingerprint` CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (`event_uuid`),
  INDEX `ix_user_occurred` (`user_uuid`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `stream_processing_error` (
  `topic` VARCHAR(249) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `partition` INT NOT NULL,
  `offset` BIGINT NOT NULL,
  `event_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  `error_code` VARCHAR(64) NOT NULL,
  `error_detail` VARCHAR(255) NOT NULL,
  `source_reference` VARCHAR(512) NOT NULL,
  `observed_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`topic`,`partition`,`offset`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
