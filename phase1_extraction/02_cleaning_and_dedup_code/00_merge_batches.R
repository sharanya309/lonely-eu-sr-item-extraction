#!/usr/bin/env Rscript
# parallel_merge.R  (updated — handles batches 1 through 9)
# Working directory: wherever your parallel_output_batchN.xlsx files live
#
# Merges ALL batch output files into one merged_all_batches.csv.
# Works for however many batches you have — automatically finds all
# files matching parallel_output_batch*.xlsx in the working directory.

library(readxl)
library(dplyr)

# ── Find all batch output files ───────────────────────────────────────────────
files <- list.files(pattern = "^parallel_output_batch.*\\.xlsx$")

if (length(files) == 0) {
  stop("No parallel_output_batch*.xlsx files found in working directory.\n",
       "Make sure you're in the right folder and all batch runs are complete.")
}

# Sort numerically by batch number so output is in order
batch_nums <- as.integer(gsub("[^0-9]", "", files))
files <- files[order(batch_nums)]

cat("Batch files found:\n")
for (i in seq_along(files)) {
  size_mb <- round(file.size(files[i]) / 1e6, 1)
  cat(sprintf("  %s  (%.1f MB)\n", files[i], size_mb))
}
cat("\n")

# ── Load and merge ─────────────────────────────────────────────────────────────
cat("Reading files...\n")
data_list <- lapply(files, function(f) {
  df <- read_excel(f)
  df$source_batch <- f   # tag each row with which batch it came from
  df
})

df <- bind_rows(data_list)
cat(sprintf("Total rows merged: %s\n\n", format(nrow(df), big.mark = ",")))

# ── Check which item column exists ───────────────────────────────────────────
item_col <- if ("item_text_english" %in% names(df)) "item_text_english" else "item_text"

# ── Per-batch summary ─────────────────────────────────────────────────────────
cat("Per-batch summary:\n")
df |>
  group_by(source_batch) |>
  summarise(
    articles  = n_distinct(filename),
    items     = sum(!is.na(.data[[item_col]]) & .data[[item_col]] != ""),
    success   = sum(extraction_status == "success",    na.rm = TRUE),
    api_error = sum(extraction_status == "api_error",  na.rm = TRUE),
    json_error= sum(extraction_status == "json_error", na.rm = TRUE),
    not_readable = sum(extraction_status == "not_readable", na.rm = TRUE),
    .groups = "drop"
  ) |>
  print(n = 20)

cat("\n")

# ── Overall summary ───────────────────────────────────────────────────────────
total_articles   <- n_distinct(df$filename)
n_with_items     <- df |>
  filter(!is.na(.data[[item_col]]), .data[[item_col]] != "") |>
  pull(filename) |> n_distinct()
n_no_items       <- total_articles - n_with_items
total_items      <- sum(!is.na(df[[item_col]]) & df[[item_col]] != "")
social_yes       <- sum(df$measures_social_connection == "YES", na.rm = TRUE)
needs_review_n   <- df |> distinct(filename, needs_review) |>
                    filter(needs_review == TRUE | needs_review == 1) |> nrow()

cat("=== OVERALL SUMMARY ===\n")
cat(sprintf("Total articles processed:     %s\n", format(total_articles, big.mark = ",")))
cat(sprintf("Articles with items:          %s\n", format(n_with_items,   big.mark = ",")))
cat(sprintf("Articles with no items:       %s\n", format(n_no_items,     big.mark = ",")))
cat(sprintf("Total items extracted:        %s\n", format(total_items,    big.mark = ",")))
cat(sprintf("Social connection YES items:  %s\n", format(social_yes,     big.mark = ",")))
cat(sprintf("Articles flagged needs_review:%s\n", format(needs_review_n, big.mark = ",")))

# ── Save ──────────────────────────────────────────────────────────────────────
write.csv(df, "merged_all_batches.csv", row.names = FALSE)
cat(sprintf("\nSaved: merged_all_batches.csv  (%s rows)\n",
            format(nrow(df), big.mark = ",")))
