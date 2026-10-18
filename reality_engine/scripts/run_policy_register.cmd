@echo off
rem Policy register over macro documents (budgets, surveys, RBI, PIB circulars); LongCat free on Go key 1. Resumable.
rem Log: reality_engine\data\logs\policy_register_docs.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.policy_register --source doc --doc-types "Union_Budget,Union Budget%%,Economic_Survey,RBI%%,State_Budget%%,PIB_Circular" --workers 24 >> reality_engine\data\logs\policy_register_docs.log 2>&1
