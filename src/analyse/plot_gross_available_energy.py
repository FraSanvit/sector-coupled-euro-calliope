import sys
import os

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from friendly_data.converters import to_df
from frictionless.package import Package

sys.path.append(os.getcwd())
from src.construct import util

ENERGY_BALANCE_GROUPS = {
    'E7000': 'Electricity',
    'H8000': 'Direct heat',
    'C0000X0350-0370': "Other fossils",
    "C0350-0370": "Other fossils",
    "P1000": "Other fossils",
    'G3000': "Natural gas",
    'W6100_6220': "Waste",
    'N900H': 'Nuclear heat',
    '^O4000.*$': "Oil",
    'S2000': "Oil",
    "^RA1.*$|^RA2.*$|^RA3.*$|^RA4.*$|^RA5.*$": 'Renewables',
    "^R5.*$|W6210": 'Biofuels',
}

ENERGY_PRODUCERS = {
    "waste_supply": "Waste",
    "biofuel_supply": "Biofuels",
    "hydro_reservoir": "Renewables",
    "hydro_run_of_river": "Renewables",
    "nuclear": "Nuclear heat",
    "open_field_pv": "Renewables",
    "roof_mounted_pv": "Renewables",
    "wind_offshore": "Renewables",
    "wind_onshore": "Renewables",
}

COLORS = {
    "Oil": "#5d5d5d",
    "Natural gas": "#b9b9b9",
    "Other fossils": "#181818",
    "Nuclear heat": "#cc0000",
    "Biofuels": "#8fce00",
    "Renewables": "#2986cc",
    "Waste": "#ce7e00",
    "Direct heat": "#f6b26b",
    "Electricity": "#2986cc"
}

NUCLEAR_HEAT_MUTIPLIER = 0.4  # We need to account for going from Nuclear electricity output to Nuclear Heat, using the technology efficiency

plt.rcParams.update({
    "svg.fonttype": 'none',
    'font.family':'sans-serif',
    'font.sans-serif':'Arial',
    "font.size": 8
})

FIGWIDTH = 4.40945


def plot_energy_bars(
    path_to_energy_balances, path_to_spores, countries, model_year, path_to_output
):
    country_subselection, input_energy = get_input_energy(
        path_to_energy_balances, countries, model_year
    )
    smallest_output_energy, biggest_spore_energy = get_output_energy(
        path_to_spores, country_subselection
    )
    all_data = pd.concat(
        [input_energy, smallest_output_energy, biggest_spore_energy],
        keys=[f"{model_year:.0f} actual", "Lowest energy\nSPORE", "Highest energy\nSPORE"],
        axis=1
    ).sort_values(f"{model_year:.0f} actual", ascending=False)

    all_data_to_plot = (
        all_data
        .div(1000)
        .where(all_data.div(all_data.sum()) > 0.005)
        .dropna(how="all")
        .T
    )
    fig, ax = plt.subplots(1, 1, figsize=(FIGWIDTH, FIGWIDTH))

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    all_data_to_plot.plot.bar(
        ax=ax, stacked=True,
        color=[COLORS[i] for i in all_data_to_plot.columns]
    )
    for tick in ax.get_xticklabels():
        tick.set_rotation(0)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        handles[::-1], labels[::-1],
        bbox_to_anchor=(1, 0.5),
        frameon=False,
        loc="center left"
    )

    sns.despine(ax=ax)
    ax.set_ylabel("1000 TWh")

    if path_to_output.endswith(".png"):
        kwargs = {"dpi": 300}
    else:
        kwargs = {}

    fig.savefig(path_to_output, bbox_inches="tight", **kwargs)


def get_input_energy(path_to_energy_balances, countries, model_year):
    annual_energy_balances = util.read_tdf(path_to_energy_balances)

    countries_alpha2 = [util.get_alpha2(i) for i in countries]

    gross_avail_energy = (
        annual_energy_balances
        .xs(("GAE", "TJ", model_year), level=("cat_code", "unit", "year"))
        .unstack()
        .reindex(countries_alpha2, axis=1)
    )
    missing_countries = gross_avail_energy.columns[gross_avail_energy.isnull().all()]
    if not missing_countries.empty:
        print(f"Missing {missing_countries} from input gross annual energy balances")

    to_group = (
        gross_avail_energy
        .index
        .to_frame()
        .squeeze()
        .replace(ENERGY_BALANCE_GROUPS, regex=True)
    )
    to_group = to_group[to_group.index != to_group.values]

    grouped_gross_avail_energy = (
        gross_avail_energy
        .groupby(to_group).sum()
        .sum(axis=1)
        .sort_values(ascending=False)
        .apply(util.tj_to_twh)
    )

    country_subselection = gross_avail_energy.dropna(how="all", axis=1).columns
    return country_subselection, grouped_gross_avail_energy


def get_output_energy(path_to_spores_data, country_subselection):

    countries = "|".join([util.get_alpha3(i) for i in country_subselection])
    primary_supply = pd.read_csv(
        os.path.join(path_to_spores_data, "data", "primary_energy_supply.csv")
    )
    primary_supply = primary_supply.set_index(list(primary_supply.columns[:-1])).squeeze()
    primary_supply_summed = (
        primary_supply[primary_supply.index.get_level_values("locs").str.contains(countries)]
        .sum(level=["carriers", "spore"])
        .drop("Net electricity import", level="carriers", errors="ignore")
        .unstack("spore")
        .rename({"Renewable electricity": "Renewables", "Nuclear electricity": "Nuclear heat"})
    )
    primary_supply_summed.loc["Nuclear heat"] /= NUCLEAR_HEAT_MUTIPLIER

    smallest_spore = primary_supply_summed.sum().idxmin()
    biggest_spore = primary_supply_summed.sum().idxmax()
    return primary_supply_summed[smallest_spore], primary_supply_summed[biggest_spore]


if __name__ == "__main__":
    plot_energy_bars(
        path_to_energy_balances=snakemake.input.energy_balances,
        path_to_spores=snakemake.input.spores,
        countries=snakemake.params.countries,
        model_year=snakemake.params.model_year,
        path_to_output=snakemake.output[0]
    )
