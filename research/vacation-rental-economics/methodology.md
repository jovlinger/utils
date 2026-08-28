# Vacation Rental Property Economics: Data Collection Methodology

Status: **In Progress**  
Todo: `036dc129` (Vacation rental property economics: purchase price vs rental income analysis)  
Last updated: 2026-08-26

## Purpose

This document describes the methodology for collecting vacation rental property data to analyze the economics of ownership. A MIDCAP agent can follow this methodology to extend the analysis to additional markets.

---

## Target Markets

| Market | Region Type | State | Notes |
|--------|-------------|-------|-------|
| Harwich Port | Cape Cod coastal | MA | High-demand summer rental area |
| Little Sebago Lake | Maine lake region | ME | Seasonal lake vacation area |
| Kennebunkport | Southern Maine coastal | ME | Upscale beach vacation area |
| Lake Winnipesaukee | NH lake region | NH | Largest lake in NH, vacation destination |

---

## Data Points Per Property

For each comparable property, collect:

### Purchase/Value Data
| Field | Source | Notes |
|-------|--------|-------|
| Address | Zillow listing | Full address for deduplication |
| List Price | Zillow | Current asking price if for sale |
| Zestimate | Zillow | Automated valuation |
| Recent Sale Price | Zillow/Public records | If sold within 2 years |
| Bedrooms | Zillow | Affects rental capacity |
| Bathrooms | Zillow | Affects rental value |
| Square Footage | Zillow | Size comparison |
| Property Type | Zillow | Single family, condo, etc. |

### Rental Income Data
| Field | Source | Notes |
|-------|--------|-------|
| Weekly High Season Rate | VRBO/WeneedaVacation | Peak summer rates |
| Weekly Shoulder Season Rate | VRBO | Spring/fall rates |
| Minimum Stay | VRBO | Affects booking flexibility |
| Review Count | VRBO | Indicator of rental history |
| Occupancy Estimate | Calculated | See formula below |

### Annual Cost Estimates
| Cost Category | Source | Calculation |
|---------------|--------|-------------|
| Mortgage Payment | Calculator | 30yr fixed at current rate, 20% down |
| Property Insurance | Regional averages | ~$1,500-3,000/year for vacation homes |
| Property Tax | Public records | Varies by town/state |
| Maintenance Reserve | Industry standard | 1% of property value per year |
| HOA/Condo Fees | Zillow listing | If applicable |
| Property Management | Industry standard | 20-30% of rental income if managed |

---

## Data Sources

### Primary Sources

#### Zillow (zillow.com)
- **Data available**: Listings, Zestimates, sale history, property details
- **Access method**: WebFetch for listing pages, or API if available
- **Rate limits**: Respect robots.txt; cache responses
- **URL pattern**: `https://www.zillow.com/homes/[location]_rb/`

#### VRBO (vrbo.com)
- **Data available**: Nightly/weekly rates, availability, reviews
- **Access method**: Requires JavaScript rendering (playwright-mcp or computerUse subagent)
- **Rate limits**: May require delays between requests
- **URL pattern**: `https://www.vrbo.com/search/keywords:[location]`

#### WeneedaVacation.com
- **Data available**: Cape Cod specific rental listings and rates
- **Access method**: WebFetch may work for static pages
- **Scope**: Cape Cod area only (Harwich Port)
- **URL pattern**: `https://www.weneedavacation.com/`

### Secondary Sources

#### County Assessor/Tax Records
- Barnstable County (Harwich Port): https://www.barnstablecounty.org/
- Cumberland County (Little Sebago): https://www.cumberlandcounty.org/
- York County (Kennebunkport): https://www.yorkcountymaine.gov/
- Belknap/Carroll County (Winnipesaukee): County assessor sites

#### Mortgage Rate Reference
- Freddie Mac Primary Mortgage Market Survey
- Current 30-year fixed rate as of data collection date

---

## Data Collection Tools

### Available in This Environment
| Tool | Use Case |
|------|----------|
| WebFetch | Static HTML pages, basic listings |
| WebSearch | Finding data source URLs, verification |
| Task (computerUse) | JavaScript-heavy sites requiring browser automation |

### Required for Full Collection
| Tool | Use Case | Status |
|------|----------|--------|
| playwright-mcp | VRBO scraping (React/JS rendered) | Not available - use computerUse subagent |
| bun headless | Alternative browser automation | Not available - use computerUse subagent |

### Workaround Strategy
For JavaScript-heavy sites (VRBO, Zillow search results), use:
1. **Task tool with computerUse subagent** - can navigate and extract data from rendered pages
2. **Manual data entry** - if automation is unavailable, document the manual process
3. **API alternatives** - check if public APIs exist (AirDNA for Airbnb data, etc.)

---

## Collection Procedure

### Step 1: Property Identification
1. Search Zillow for the target market
2. Filter: Single family homes or condos, 2-4 bedrooms
3. Select 10 properties representative of the market (mix of price points)
4. Record property URLs for detailed data extraction

### Step 2: Property Value Data
For each property:
1. Navigate to Zillow listing page
2. Extract: Address, price, Zestimate, beds, baths, sqft
3. Check "Price History" for recent sale data
4. Record source URL and access date

### Step 3: Rental Income Data
For each property (or comparable nearby properties):
1. Search VRBO/WeneedaVacation for similar properties
2. Match by: Location, bedroom count, amenities
3. Extract: Weekly rates for high season (June-August)
4. Note review count as activity indicator

### Step 4: Cost Research
One-time per market:
1. Research current 30-year mortgage rate
2. Find typical property insurance costs for vacation homes
3. Look up property tax rates by town/county
4. Document maintenance reserve assumption (1% of value)

### Step 5: Calculation
For each property, calculate:
```
Annual Rental Income = (High Season Weeks × Rate × Occupancy%) + 
                       (Shoulder Season Weeks × Rate × Occupancy%)

Annual Costs = Mortgage + Insurance + Property Tax + Maintenance + Management

Net Cash Flow = Annual Rental Income - Annual Costs
```

Occupancy assumptions:
- High season (12 weeks): 85% occupancy
- Shoulder season (8 weeks): 50% occupancy
- Off season: Assume owner use or minimal rental

---

## Output Format

### Summary Table (Deliverable 1)

| Location | Avg Purchase Price | Avg Annual Rental | Avg Annual Costs | Net Cash Flow |
|----------|-------------------|-------------------|------------------|---------------|
| Harwich Port MA | $XXX,XXX | $XX,XXX | $XX,XXX | $(X,XXX) |
| Little Sebago ME | $XXX,XXX | $XX,XXX | $XX,XXX | $(X,XXX) |
| Kennebunkport ME | $XXX,XXX | $XX,XXX | $XX,XXX | $(X,XXX) |
| Lake Winnipesaukee NH | $XXX,XXX | $XX,XXX | $XX,XXX | $(X,XXX) |

### Raw Data Appendix (Deliverable 2)
- Per-property data in CSV or markdown table format
- Source URLs with access dates
- Calculation details

---

## Extending to Other Markets

To apply this methodology to a new vacation rental market:

1. **Identify the market type** (coastal, lake, mountain, etc.)
2. **Locate data sources** - Zillow works nationwide; find local rental listing sites
3. **Adjust assumptions** - High season timing varies by market
4. **Research local costs** - Insurance and taxes vary significantly by state
5. **Follow the same collection procedure** outlined above

Key factors that vary by market:
- Seasonality (summer beach vs winter ski)
- High season length
- Property price range
- Rental management availability
- Local regulations (short-term rental restrictions)

---

## Limitations

1. **Data timeliness**: Real estate data changes daily; capture timestamps
2. **Occupancy estimates**: Actual occupancy varies; used industry averages
3. **Property matching**: Rental comps may not exactly match sale listings
4. **Management costs**: Varies if owner-managed vs professionally managed
5. **Financing assumptions**: Assumes 20% down, 30-year fixed; actual varies
6. **Local regulations**: Some areas restrict short-term rentals; not factored

---

## Provenance Template

For each data point, record:
```
Source: [URL]
Access Date: [YYYY-MM-DD]
Data Type: [listing/rate/tax record]
Notes: [any caveats or transformations applied]
```
