# item cleaning pipeline with 2-step deduplication

library(tidyverse)
library(readxl)
library(writexl)

set.seed(123)
dir.create("output", showWarnings = FALSE)

INPUT_FILE <- "merged_all_batches.csv"

# step 1: remove errors and incomplete items
data <- read.csv(INPUT_FILE)

cleaned <- data %>%
  filter(
    needs_review == 0,
    extraction_status == "success",
    !is.na(item_text_english)
  )

removed1 <- data %>%
  filter(
    needs_review == 1 | 
      extraction_status != "success" | 
      is.na(item_text_english)
  )

write_xlsx(cleaned, "output/step1_cleaned.xlsx")
write_xlsx(removed1, "output/step1_removed.xlsx")

cat("step 1:", nrow(data), "->", nrow(cleaned), "\n")

# step 2a: deduplicate scales globally

cleaned$row_id <- 1:nrow(cleaned)
cleaned$scale_clean <- tolower(trimws(cleaned$scale_name))
cleaned$scale_clean <- gsub("\\s+", " ", cleaned$scale_clean)

# scale names to exclude from deduplication
generic_scales <- c(
  "demographics", "demographic questions", "demographic items",
  "contextual variables", "contextual items", "contextual questions",
  "background variables", "background questions",
  "single items", "single item measures"
)

cleaned$is_generic <- cleaned$scale_clean %in% generic_scales

# create unique identifier for each scale occurrence
cleaned$scale_occurrence_id <- paste0(
  cleaned$scale_name, "_",
  cleaned$title, "_",
  cleaned$filename
)

# count items per occurrence
cleaned <- cleaned %>%
  group_by(scale_occurrence_id) %>%
  mutate(items_in_this_occurrence = n()) %>%
  ungroup()

# find duplicate scales (exclude generic names)
# when duplicate scale found, keep ALL items from occurrence with most items
cleaned <- cleaned %>%
  group_by(scale_clean) %>%
  mutate(
    scale_dup_group = cur_group_id(),
    scale_occurrences = n_distinct(scale_occurrence_id),
    scale_is_duplicate = n_distinct(scale_occurrence_id) > 1 & !is_generic,
    scale_rank = dense_rank(desc(items_in_this_occurrence))
  ) %>%
  ungroup() %>%
  mutate(keep_scale = is_generic | scale_rank == 1)

# create scale mapping
scale_map <- cleaned %>%
  filter(scale_is_duplicate) %>%
  select(scale_dup_group, scale_occurrence_id, scale_name, title, 
         items_in_this_occurrence, keep_scale, scale_occurrences) %>%
  distinct() %>%
  arrange(scale_dup_group, desc(keep_scale))

deduplicated_scales <- cleaned %>% filter(keep_scale)
removed2a <- cleaned %>% filter(!keep_scale)

write_xlsx(deduplicated_scales, "output/step2a_deduplicated_scales.xlsx")
write_xlsx(removed2a, "output/step2a_removed_duplicate_scales.xlsx")
write_xlsx(scale_map, "output/step2a_scale_mapping.xlsx")

cat("step 2a:", nrow(cleaned), "->", nrow(deduplicated_scales), "\n")

# step 2b: deduplicate items
deduplicated_scales$origin_id <- paste0(
  deduplicated_scales$scale_occurrence_id, "_",
  ifelse(is.na(deduplicated_scales$subscale), "none", deduplicated_scales$subscale), "_",
  ifelse(is.na(deduplicated_scales$item_number), deduplicated_scales$row_id, deduplicated_scales$item_number)
)

deduplicated_scales$item_clean <- tolower(trimws(deduplicated_scales$item_text_english))
deduplicated_scales$item_clean <- gsub("\\s+", " ", deduplicated_scales$item_clean)

# find duplicate items
deduplicated_scales <- deduplicated_scales %>%
  group_by(item_clean) %>%
  mutate(
    item_dup_group = cur_group_id(),
    item_dup_count = n(),
    item_is_duplicate = n() > 1
  ) %>%
  ungroup()

# keep first from largest scale
deduplicated_scales <- deduplicated_scales %>%
  mutate(scale_size = ifelse(is.na(items_extracted_count), 0, items_extracted_count)) %>%
  arrange(item_clean, desc(scale_size), row_id) %>%
  group_by(item_clean) %>%
  mutate(
    item_rank = row_number(),
    keep_item = item_rank == 1
  ) %>%
  ungroup()

# create item mapping
item_map <- deduplicated_scales %>%
  filter(item_is_duplicate) %>%
  select(item_dup_group, row_id, origin_id, scale_occurrence_id, 
         scale_name, subscale, item_text_english, keep_item, item_dup_count) %>%
  arrange(item_dup_group, desc(keep_item))

deduplicated_items <- deduplicated_scales %>% filter(keep_item)
removed2b <- deduplicated_scales %>% filter(!keep_item)

write_xlsx(deduplicated_items, "output/step2b_deduplicated_items.xlsx")
write_xlsx(removed2b, "output/step2b_removed_duplicate_items.xlsx")
write_xlsx(item_map, "output/step2b_item_mapping.xlsx")

cat("step 2b:", nrow(deduplicated_scales), "->", nrow(deduplicated_items), "\n")

# step 3: keep only social connection items
social <- deduplicated_items %>%
  filter(measures_social_connection == "YES")

removed3 <- deduplicated_items %>%
  filter(measures_social_connection != "YES" | is.na(measures_social_connection))

write_xlsx(social, "output/step3_social_items.xlsx")
write_xlsx(removed3, "output/step3_removed_non_social.xlsx")

cat("step 3:", nrow(deduplicated_items), "->", nrow(social), "\n")

# step 4: keep only necessary columns
final <- social %>%
  select(
    row_id,
    origin_id,
    scale_occurrence_id,
    scale_dup_group,
    item_dup_group,
    title,
    country_study,
    scale_name,
    subscale,
    item_text_original,
    item_text_english
  )

write_xlsx(final, "output/step4_final.xlsx")

cat("final:", nrow(final), "items\n")