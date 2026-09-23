import os
import glob
from datetime import datetime

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BLS_API_KEY = os.getenv('BLS_API_KEY')
BLS_URL = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'

# Government (999) codes -- OEWS does not classify government by NAICS. These are
# the 'including schools/hospitals/USPS' variants.
GOV = {
    '999001': 'Federal, State, and Local Government, including State and Local Government Schools and Hospitals and the U.S. Postal Service (OEWS Designation)',
    '999101': 'Federal Government, including the U.S. Postal Service (OEWS Designation)',
    '999201': 'State Government, including Schools and Hospitals (OEWS Designation)',
    '999301': 'Local Government, including Schools and Hospitals (OEWS Designation)',
}


def _structure(path=None):
    """The 2022 NAICS structure (all levels, code + title). Small static file."""
    if path is None:
        hits = glob.glob('*NAICS_Structure*.csv')
        if not hits:
            raise FileNotFoundError('No NAICS structure CSV (*NAICS_Structure*.csv) found.')
        path = sorted(hits)[0]
    df = pd.read_csv(path, dtype=str)
    df.columns = ['code', 'title']
    df['title'] = df['title'].str.strip()
    # aggregate levels carry a trailing 'T' marker; 6-digit titles do not
    agg = df['code'].str.len() < 6
    df.loc[agg, 'title'] = df.loc[agg, 'title'].str.replace(r'T$', '', regex=True).str.strip()
    return df


def _pad6(code):
    """OEWS 6-char industry code: NAICS significant digits, right-padded with 0."""
    return code + '0' * (6 - len(code))


def _industry_series(code6, occ='000000', datatype='04'):
    """OEWS national series ID for an industry (all occupations, annual mean wage)."""
    return 'OEUN0000000' + code6 + occ + datatype


def _fetch_wages(series_ids, start_year, end_year):
    """Query the BLS API for series IDs; return {seriesID: latest wage} (newest year)."""
    out = {}
    for i in range(0, len(series_ids), 50):          # 50 series per request with a key
        chunk = series_ids[i:i + 50]
        payload = {'seriesid': chunk, 'startyear': str(start_year), 'endyear': str(end_year)}
        if BLS_API_KEY:
            payload['registrationkey'] = BLS_API_KEY
        r = requests.post(BLS_URL, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get('status') != 'REQUEST_SUCCEEDED':
            raise RuntimeError(f"BLS API error: {data.get('message')}")
        for s in data['Results']['series']:
            if s['data']:                            # newest data point first
                w = pd.to_numeric(s['data'][0]['value'], errors='coerce')
                if pd.notna(w):
                    out[s['seriesID']] = float(w)
    return out


def naics_wage_lookup(year=None):
    """{level: {naics_code: mean_annual_wage}} for 3/4/5/6-digit, from the BLS API.

    The API only holds the latest OEWS year, so it queries a two-year window and
    takes the newest data point. Keyed by the original NAICS code at each level.
    """
    year = year or datetime.now().year
    struct = _structure()
    levels = {6: {}, 5: {}, 4: {}, 3: {}}

    series_to_code = {}
    for length in levels:
        for c in struct.loc[struct['code'].str.len() == length, 'code']:
            series_to_code[_industry_series(_pad6(c))] = (length, c)

    wages = _fetch_wages(list(series_to_code), year - 1, year)
    for sid, w in wages.items():
        length, code = series_to_code[sid]
        levels[length][code] = w
    return levels


def naics_industry_wages(year=None):
    """Mean annual wage per published NAICS industry (all occupations), 4/5/6-digit."""
    levels = naics_wage_lookup(year)
    titles = dict(zip(_structure()['code'], _structure()['title']))
    rows = []
    for length in (4, 5, 6):
        for code, wage in levels[length].items():
            rows.append({'code': _pad6(code), 'title': titles.get(code, ''), 'wage': wage})
    return pd.DataFrame(rows).sort_values('code').reset_index(drop=True)


def naics_6digit_backfilled(year=None):
    """Every 6-digit NAICS code with a wage, filled 6 -> 5 -> 4 -> 3 digit (API).

    NAICS 92 (government) is excluded -- OEWS does not classify government by
    NAICS. The 2-digit sector level is not published in the BLS API, so the
    backfill stops at 3-digit; codes with no wage at 3/4/5/6-digit stay blank.
    """
    struct = _structure()
    six = struct[struct['code'].str.len() == 6].copy()
    six = six[six['code'].str[:2] != '92']  # skip government (no OEWS NAICS wage)

    levels = naics_wage_lookup(year)

    def resolve(c):
        if c in levels[6]:
            return levels[6][c], '6-digit', _pad6(c)
        if c[:5] in levels[5]:
            return levels[5][c[:5]], '5-digit', _pad6(c[:5])
        if c[:4] in levels[4]:
            return levels[4][c[:4]], '4-digit', _pad6(c[:4])
        if c[:3] in levels[3]:
            return levels[3][c[:3]], '3-digit', _pad6(c[:3])
        return None, None, None

    res = six['code'].apply(resolve)
    six['wage'] = [r[0] for r in res]
    six['wage_source_level'] = [r[1] for r in res]
    six['wage_source_naics'] = [r[2] for r in res]
    return six[['code', 'title', 'wage',
                'wage_source_level', 'wage_source_naics']].reset_index(drop=True)


def government_wages(year=None):
    """OEWS government wages (999 designation codes, all occupations), from the API."""
    year = year or datetime.now().year
    series = {_industry_series(code): code for code in GOV}
    wages = _fetch_wages(list(series), year - 1, year)
    rows = [{'code': code, 'title': GOV[code], 'wage': wages.get(sid)}
            for sid, code in series.items()]
    return pd.DataFrame(rows).sort_values('code').reset_index(drop=True)


if __name__ == '__main__':
    # NAICS industry wages (4/5/6-digit) -- from the BLS API
    naics = naics_industry_wages()
    naics.to_csv('naics_wages.csv', index=False)
    print(f'NAICS: {len(naics)} rows -> naics_wages.csv')

    # NAICS 6-digit, wage backfilled 6 -> 5 -> 4 -> 3 digit
    six = naics_6digit_backfilled()
    six.to_csv('naics_6digit_wages.csv', index=False)
    filled = six['wage'].notna().sum()
    print(f'NAICS 6-digit: {len(six)} rows -> naics_6digit_wages.csv '
          f'({filled} filled, {len(six) - filled} blank)')
    print(six['wage_source_level'].value_counts(dropna=False).to_string())

    # Government (999 codes)
    gov = government_wages()
    gov.to_csv('government_wages.csv', index=False)
    print(f'\nGovernment: {len(gov)} rows -> government_wages.csv')
