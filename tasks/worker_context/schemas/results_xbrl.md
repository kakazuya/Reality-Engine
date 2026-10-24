# results_xbrl schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\results_xbrl.db` (6.1 GB)

NSE quarterly-results XBRL store: filing registry, long facts and a pivoted quarterly view. Authoritative for reported quarterly financials; monetary values are in rupees.

## facts
rows: 13.9M · key columns: file, context, concept

- `file` TEXT
- `concept` TEXT
- `context` TEXT
- `period_start` TEXT
- `period_end` TEXT
- `instant` TEXT
- `value` REAL
- `unit` TEXT
- `decimals` TEXT

## filings
rows: 106.6k · key columns: file, isin, symbol

- `file` TEXT
- `taxonomy` TEXT
- `xbrl_url` TEXT
- `isin` TEXT
- `symbol` TEXT
- `scrip_code` TEXT
- `company` TEXT
- `index_period` TEXT
- `reporting_quarter` TEXT
- `consolidated` TEXT
- `audited` TEXT
- `period_start` TEXT
- `period_end` TEXT
- `fy_start` TEXT
- `fy_end` TEXT
- `board_meeting` TEXT
- `broadcast_ts` TEXT
- `dissem_ts` TEXT
- `filing_ts` TEXT
- `audit_opinion` TEXT
- `n_facts` INTEGER
- `status` TEXT
- `parsed_at` TEXT

## filings_isin
rows: ~183.0k · key columns: file

- `file` TEXT
- `isin_filed` TEXT
- `isin` TEXT
- `method` TEXT
- `same_issuer` INTEGER
- `as_of` TEXT
- `resolved_at` TEXT

## quarterly
rows: ? · key columns: file, isin, symbol, period_end

- `file` TEXT
- `taxonomy` TEXT
- `isin` TEXT
- `symbol` TEXT
- `scrip_code` TEXT
- `company` TEXT
- `consolidated` TEXT
- `audited` TEXT
- `period_start` TEXT
- `period_end` TEXT
- `index_period` TEXT
- `reporting_quarter` TEXT
- `board_meeting` TEXT
- `dissem_ts` TEXT
- `broadcast_ts` TEXT
- `RevenueFromOperations`
- `OtherIncome`
- `Income`
- `CostOfMaterialsConsumed`
- `EmployeeBenefitExpense`
- `FinanceCosts`
- `DepreciationDepletionAndAmortisationExpense`
- `OtherExpenses`
- `Expenses`
- `ProfitBeforeExceptionalItemsAndTax`
- `ExceptionalItemsBeforeTax`
- `ProfitBeforeTax`
- `TaxExpense`
- `ProfitLossForPeriodFromContinuingOperations`
- `ProfitLossForPeriod`
- `ProfitOrLossAttributableToOwnersOfParent`
- `ComprehensiveIncomeForThePeriod`
- `BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations`
- `DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations`
- `PaidUpValueOfEquityShareCapital`
- `FaceValueOfEquityShareCapital`
