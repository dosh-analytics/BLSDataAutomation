import os
from datetime import datetime

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BLS_API_KEY = os.getenv('BLS_API_KEY')
SOC_CACHE = 'soc_codes.csv'


def get_soc_code():
    if os.path.exists(SOC_CACHE):
        df = pd.read_csv(SOC_CACHE, dtype=str)
    else:
        df = pd.read_excel('occupation_definitions_m2024.xlsx').rename(columns={
            'May 2024 OEWS Estimates Code': 'soc_code',
            'May 2024 OEWS Estimates Title': 'title',
        })[['soc_code', 'title']]
        df = df[df['soc_code'].str.match(r'^\d\d-\d{4}$', na=False)]
        df.to_csv(SOC_CACHE, index=False)
    return df['soc_code'].str.replace('-', '', regex=False)


def oews_occupation_wages(soc_codes, start_year, end_year):
    series_ids = [f'OEUN0000000000000{soc}04' for soc in soc_codes]
    all_dfs = []
    for i in range(0, len(series_ids), 50):
        chunk = series_ids[i:i+50]
        response = requests.post('https://api.bls.gov/publicAPI/v2/timeseries/data/',
            json={
                'seriesid': chunk,
                'startyear': start_year,
                'endyear': end_year,
                'registrationkey': BLS_API_KEY
            })
        all_dfs.append(oews_parser(response.json()))
    df = pd.concat(all_dfs, ignore_index=True)
    return decode_oews(df)


def oews_parser(json):
    table = []
    for series in json['Results']['series']:
        seriesID = series['seriesID']
        for obs in series['data']:
            year = obs['year']
            val = obs['value']
            table.append({
                'SeriesID': seriesID,
                'Year': year,
                'Value': val
            })
    return pd.DataFrame(table)


def decode_oews(df):
    df['occ_6']         = df['SeriesID'].str[17:23]
    df['datatype_code'] = df['SeriesID'].str[23:25]

    df['soc'] = df['occ_6'].str[:2] + '-' + df['occ_6'].str[2:]

    df['datatype'] = df['datatype_code'].map({
        '04': 'mean_annual_wage'
    })

    df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
    df = df.drop(columns=['SeriesID', 'occ_6', 'datatype_code'])

    df_pivot = df.pivot_table(
        index=['soc', 'Year'],
        columns='datatype',
        values='Value'
    ).reset_index()

    soc_titles = pd.read_csv(SOC_CACHE, dtype=str)[['soc_code', 'title']]
    df_pivot = df_pivot.merge(soc_titles, left_on='soc', right_on='soc_code', how='left')
    df_pivot = df_pivot.drop(columns=['soc_code'])

    df_pivot = df_pivot[['soc', 'title', 'Year', 'mean_annual_wage']]

    # sort numerically by soc code — strip dash and convert to int for sorting
    df_pivot['soc_numeric'] = df_pivot['soc'].str.replace('-', '', regex=False).astype(int)
    df_pivot = df_pivot.sort_values(['soc_numeric', 'Year']).drop(columns=['soc_numeric'])

    # reindex from 0
    df_pivot = df_pivot.reset_index(drop=True)

    return df_pivot


if __name__ == '__main__':
    # SOC: wage per occupation, all industries -- from the BLS API.
    # The API only returns the latest OEWS year, so end at the current year.
    soc_codes = get_soc_code()
    soc = oews_occupation_wages(soc_codes, datetime.now().year - 1, datetime.now().year)
    soc = soc[['soc', 'title', 'mean_annual_wage']].rename(
        columns={'soc': 'code', 'title': 'title', 'mean_annual_wage': 'wage'})
    soc.to_csv('soc_wages.csv', index=False)
    print(f'SOC: {len(soc)} rows -> soc_wages.csv')
