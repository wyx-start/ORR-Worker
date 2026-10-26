"""Recorded reference presets; values apply only at their specified temperature."""
REFERENCE_PRESETS = {
    "自定义 / 实测标定": None,
    "Ag/AgCl · 饱和 KCl · 25 °C": ("Ag/AgCl", "饱和 KCl", .197, "https://www.metrohm.com/content/dam/metrohm/shared/documents/white-papers/WP-002EN.pdf"),
    "Ag/AgCl · 3 M KCl · 25 °C": ("Ag/AgCl", "3 M KCl", .207, "https://www.metrohm.com/content/dam/metrohm/shared/documents/white-papers/WP-002EN.pdf"),
    "SCE · 饱和 KCl · 25 °C": ("SCE", "饱和 KCl", .241, "https://www.metrohm.com/en_be/service/product-help-center/voltammetry/voltammetry---faqs.html"),
    "Hg/HgO · 1 M KOH · Pine 25 °C 近似值": ("Hg/HgO", "1 M KOH", .110, "https://pineresearch.com/tools/reference-electrode-conversion-calculator/"),
}
