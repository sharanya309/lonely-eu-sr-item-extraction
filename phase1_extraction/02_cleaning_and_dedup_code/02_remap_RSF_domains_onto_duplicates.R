# apply categories to all duplicates

library(tidyverse)
library(readxl)
library(writexl)

FINAL_WITH_CATEGORIES <- "step4_final_with_categories.xlsx"

# load categorized items
categorized <- read_excel(FINAL_WITH_CATEGORIES)

if(!"assigned_category" %in% names(categorized)) {
  stop("file needs column: assigned_category")
}

# apply to item duplicates
item_map <- read_excel("output/step2b_item_mapping.xlsx")

queens <- item_map %>%
  filter(keep_item) %>%
  select(item_dup_group, row_id) %>%
  left_join(
    categorized %>% select(row_id, assigned_category),
    by = "row_id"
  )

item_map_with_cats <- item_map %>%
  left_join(
    queens %>% select(item_dup_group, assigned_category),
    by = "item_dup_group"
  )

# apply to scale duplicates
removed_scales <- read_excel("output/step2a_removed_duplicate_scales.xlsx")

removed_scales$item_clean <- tolower(trimws(removed_scales$item_text_english))
removed_scales$item_clean <- gsub("\\s+", " ", removed_scales$item_clean)

category_lookup <- categorized %>%
  mutate(
    item_clean = tolower(trimws(item_text_english)),
    item_clean = gsub("\\s+", " ", item_clean)
  ) %>%
  select(item_clean, assigned_category)

removed_scales_with_cats <- removed_scales %>%
  left_join(category_lookup, by = "item_clean") %>%
  select(row_id, origin_id, scale_occurrence_id, scale_name, subscale, 
         item_text_english, assigned_category)

# combine all
all_items_with_cats <- bind_rows(
  categorized %>% 
    select(row_id, origin_id, scale_occurrence_id, scale_name, subscale, 
           item_text_english, assigned_category) %>%
    mutate(item_status = "kept_item"),
  
  item_map_with_cats %>% 
    filter(!keep_item) %>%
    select(row_id, origin_id, scale_occurrence_id, scale_name, subscale, 
           item_text_english, assigned_category) %>%
    mutate(item_status = "duplicate_item"),
  
  removed_scales_with_cats %>%
    mutate(item_status = "duplicate_scale")
)

write_xlsx(all_items_with_cats, "output/all_items_with_categories.xlsx")

cat("total:", nrow(all_items_with_cats), "items with categories\n")