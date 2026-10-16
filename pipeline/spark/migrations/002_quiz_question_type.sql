-- Existing databases only: run once before deploying the QUIZ Std 1.1 writer.
-- Existing rows retain every original value, question_type is NULL for history.
-- New Std 1.0 rows are mapped to MULTIPLE_CHOICE by Spark, without changing Std.
ALTER TABLE `quiz_attempt_fact`
  ADD COLUMN `question_type` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER `content_uuid`,
  MODIFY COLUMN `choice_uuid` CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL;
