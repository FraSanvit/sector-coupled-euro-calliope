import pandas as pd

import util

EFFICIENCY_QUANTILE = 0.25

CARRIERS = {
    'O4652XR5210B': 'petrol',
    'R5210B': 'biofuels',
    'O4671XR5220B': 'diesel',
    'R5220B': 'biofuels',
    'O4630': 'lpg',
    'G3000': 'natural_gas',
    'E7000': 'electricity'
}
idx = pd.IndexSlice

YEAR_RANGE = slice(2000, 2018)


def get_transport_demand(
    energy_balances_path, jrc_road_energy_path, jrc_road_distance_path, jrc_road_vehicles_path,
    jrc_rail_energy_path, jrc_rail_distance_path, road_distance_out_path, road_vehicles_out_path,
    road_efficiency_out_path, rail_energy_out_path, air_energy_out_path,
    marine_energy_out_path, road_bau_electricity_out_path, rail_bau_electricity_out_path
):
    energy_balances = util.read_tdf(energy_balances_path)
    road_energy_df = util.read_tdf(jrc_road_energy_path)
    road_distance_df = util.read_tdf(jrc_road_distance_path)
    road_vehicles_df = util.read_tdf(jrc_road_vehicles_path)
    rail_energy_df = util.read_tdf(jrc_rail_energy_path)
    rail_distance_df = util.read_tdf(jrc_rail_distance_path)

    # Add transport energy demand from agriculture and 'not elsewhere specified' (military)
    # assumption: agriculture oil use goes to 'road' transport demand;
    # fisheries' oil use goes to marine fuel demand;
    # 'not elsewhere specified' oil use goes predominantly to 'road' transport, except kerosene which goes to aviation
    other_transport_aviation = (  # all kerosene from the military destined for aviation
        energy_balances
        .loc[idx['FC_OTH_NSP_E', ['O4651', 'O4653', 'O4661XR5230B', 'O4669'], :, :, :]]
        .sum(level=['country', 'year'])
    )
    other_transport_road = (  # i.e. all oil that isn't destined for aviation
        energy_balances
        .loc[idx[['FC_OTH_AF_E', 'FC_OTH_NSP_E'], 'O4000XBIO', :, :, :]]
        .sum(level=['country', 'year'])
        .sub(other_transport_aviation, fill_value=0)  # remove fuel use assumed for aviation
        .to_frame('diesel')
        .rename_axis(columns='carrier')
        .stack()
    )
    other_transport_marine = (  # i.e. all fisheries' oil use
        energy_balances
        .loc[idx[['FC_OTH_FISH_E'], 'O4000XBIO', :, :, :]]
        .sum(level=['country', 'year'])
    )

    total_road_distance, road_efficiency, road_bau_consumption = get_all_distance_efficiency(
        energy_balances, 'FC_TRA_ROAD_E', road_energy_df,
        road_distance_df, 'vehicle_subtype', other_transport_road
    )
    total_road_vehicles, total_road_distance = get_all_vehicles(
        road_distance_df, road_vehicles_df, total_road_distance
    )
    # Some cleanup that's specific to road data
    road_efficiency = (
        # 25th percentile of 2015 efficiency in TWh/mio km
        (1 / road_efficiency.xs(2015, level='year'))
        .unstack(['vehicle_type', 'vehicle_subtype'])
        .quantile(EFFICIENCY_QUANTILE)
        .unstack(0)
        .groupby({
            'Diesel oil engine': 'diesel',
            'Battery electric vehicles': 'electricity',
            'Domestic': 'diesel',
            'International': 'diesel',
            'Gasoline engine': 'petrol',
            'Plug-in hybrid electric': 'petrol'
        }).mean()
        .assign(unit='twh_per_mio_km').set_index('unit', append=True)
        .stack()
    )
    road_electricity_bau = (
        road_bau_consumption
        .sum(level=['carrier', 'vehicle_type', 'country_code', 'year', 'unit'])
        .xs('electricity')
    )
    total_rail_distance, rail_efficiency, rail_bau_consumption = get_all_distance_efficiency(
        energy_balances, 'FC_TRA_RAIL_E', rail_energy_df, rail_distance_df, 'carrier'
    )
    # Some cleanup that's specific to rail data
    rail_energy = (
        # historical energy consumption -> historical distance
        rail_bau_consumption.droplevel('unit')
        .mul(rail_efficiency.droplevel('unit'))    # efficiency = distance/energy
        .sum(level=['vehicle_type', 'section', 'country_code', 'year'])
        # historical distance -> total electricity demand
        .div(rail_efficiency.xs('electricity', level='carrier').droplevel('unit'))
        .sum(level=['vehicle_type', 'country_code', 'year'])
        .to_frame('twh')
        .rename_axis(columns='unit')
        .stack()
    )
    rail_electricity_bau = (
        rail_bau_consumption
        .sum(level=['carrier', 'section', 'country_code', 'year', 'unit'])
        .xs('electricity')
    )
    # High speed and metro are all electrified, so bau_electricity == eurocalliope_electricity
    assert abs(
        (rail_energy - rail_bau_consumption.xs('electricity', level='carrier'))
        [['High speed passenger trains', 'Metro and tram, urban light rail']]
    ).max() < 1e-10

    # Air and shipping energy
    air_energy = get_marine_aviation(
        energy_balances.loc[['FC_TRA_DAVI_E', 'INTAVI']],
        other_transport_aviation
    )
    marine_energy = get_marine_aviation(
        energy_balances.loc[['INTMARB', 'FC_TRA_DNAVI_E']],
        other_transport_marine
    )

    total_road_distance.to_csv(road_distance_out_path)
    total_road_vehicles.to_csv(road_vehicles_out_path)
    road_efficiency.to_csv(road_efficiency_out_path)
    rail_energy.to_csv(rail_energy_out_path)
    air_energy.to_csv(air_energy_out_path)
    marine_energy.to_csv(marine_energy_out_path)
    road_electricity_bau.to_csv(road_bau_electricity_out_path)
    rail_electricity_bau.to_csv(rail_bau_electricity_out_path)


def get_all_distance_efficiency(
    energy_balances, cat_name, energy_df, distance_df, unique_dim, other_transport_road=0
):

    transport_energy_balance = (
        energy_balances
        .xs(cat_name)
        .unstack('carrier_code')
        .groupby(CARRIERS, axis=1).sum(min_count=1)
        .rename_axis(columns='carrier')
        .droplevel('unit')
        .stack()
        .add(other_transport_road, fill_value=0)
        .apply(util.tj_to_twh)
        .rename_axis(index=['country_code', 'year', 'carrier'])
        .unstack("year")
        .loc[:, YEAR_RANGE]
        .interpolate(axis=1, limit_direction="both")
        .stack()
    )

    # contribution of each transport mode to carrier consumption from JRC_IDEES
    # 2016-2018 from 2015 data; non-JRC countries, based on neighbour data
    carrier_contribution = fill_missing_countries_and_years(
        energy_df
        .div(energy_df.sum(level=['carrier', 'country_code', 'year']))
    )
    # Energy consumption per transport mode by mapping transport mode
    # carrier contributions to total carrier consumption
    transport_energy_per_mode = carrier_contribution.mul(transport_energy_balance).dropna()

    # Distance per unit energy consumed per transport mode according to JRC IDEES
    # 2016-2018 from 2015 data; non-JRC countries, based on neighbour data
    transport_efficiency = fill_missing_countries_and_years(
        distance_df
        .where(distance_df > 0)
        .div(
            energy_df
            .where(energy_df > 0)
            .sum(level=['country_code', unique_dim, 'section', 'vehicle_type', 'year'])
        )
    )
    # Distance travelled per transport mode, including years 2016-2018,
    # based on JRC IDEES transport efficiency (2015 data for 2016-2018)
    transport_distance_all_years = (
        transport_energy_per_mode
        .sum(level=['country_code', unique_dim, 'section', 'vehicle_type', 'year'])
        .mul(transport_efficiency)
    )
    # Use the distance traveled based on Eurostat to fill in blanks in JRC data
    aligned_dfs = (
        transport_distance_all_years
        .reorder_levels(distance_df.index.names)
        .align(distance_df)
    )
    total_transport_distance = (
        aligned_dfs[1]
        .fillna(aligned_dfs[0])
        .sum(level=['vehicle_type', unique_dim, 'country_code', 'unit', 'year'])
    )
    return total_transport_distance, transport_efficiency, transport_energy_per_mode


def get_all_vehicles(jrc_road_distance, jrc_road_vehicles, total_road_distance):
    total_vehicle_distance = fill_missing_countries_and_years(
        jrc_road_vehicles
        .droplevel('unit')
        .div(jrc_road_distance.droplevel('unit'))
    )
    total_road_vehicles = total_road_distance.mul(
        total_vehicle_distance
        .mean(level=['vehicle_type', 'vehicle_subtype', 'country_code', 'year'])
    )
    total_road_distance = total_road_distance.sum(
        level=['vehicle_type', 'country_code', 'unit', 'year']
    )
    total_road_vehicles = total_road_vehicles.sum(
        level=['vehicle_type', 'country_code', 'unit', 'year']
    ).rename({'mio_km': 'vehicles'}, level='unit')

    return total_road_vehicles, total_road_distance


def fill_missing_countries_and_years(jrc_data):
    jrc_data = jrc_data.unstack('country_code')
    balkan_countries = jrc_data[['BG', 'HR', 'HU', 'RO', 'EL']].mean(axis=1)
    nordic_countries = jrc_data[['SE', 'DK']].mean(axis=1)
    ch_neighbours = jrc_data[['DE', 'AT', 'FR', 'IT']].mean(axis=1)
    jrc_data = jrc_data.assign(
        AL=balkan_countries,
        BA=balkan_countries,
        ME=balkan_countries,
        MK=balkan_countries,
        RS=balkan_countries,
        NO=nordic_countries,
        IS=nordic_countries,
        CH=ch_neighbours,
    ).stack().unstack('year')
    jrc_data = jrc_data.assign(
        **{str(i): jrc_data[2015] for i in range(2016, 2019)}
    )
    jrc_data.columns = jrc_data.columns.astype(int)
    return jrc_data.stack()


def get_marine_aviation(energy_balances, other_energy):
    return (
        energy_balances
        .unstack('carrier_code')
        ['O4000XBIO']
        .sum(level=['country', 'year'])
        .add(other_energy, fill_value=0)
        .apply(util.tj_to_twh)
        .unstack("year")
        .interpolate(axis=1, limit_direction="both")
        .stack()
        .to_frame('twh')
        .rename_axis(columns='unit')
        .stack()
    )


if __name__ == "__main__":
    get_transport_demand(
        energy_balances_path=snakemake.input.energy_balances,
        jrc_road_energy_path=snakemake.input.jrc_road_energy,
        jrc_road_distance_path=snakemake.input.jrc_road_distance,
        jrc_road_vehicles_path=snakemake.input.jrc_road_vehicles,
        jrc_rail_energy_path=snakemake.input.jrc_rail_energy,
        jrc_rail_distance_path=snakemake.input.jrc_rail_distance,
        road_distance_out_path=snakemake.output.distance,
        road_vehicles_out_path=snakemake.output.vehicles,
        road_efficiency_out_path=snakemake.output.efficiency,
        rail_energy_out_path=snakemake.output.rail_energy,
        air_energy_out_path=snakemake.output.air_energy,
        marine_energy_out_path=snakemake.output.marine_energy,
        road_bau_electricity_out_path=snakemake.output.road_bau_electricity,
        rail_bau_electricity_out_path=snakemake.output.rail_bau_electricity,
    )
