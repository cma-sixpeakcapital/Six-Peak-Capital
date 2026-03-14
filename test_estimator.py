"""Quick test of the construction estimator module."""

from construction_estimator.database import HistoricalDatabase
from construction_estimator.estimator import EstimatorEngine

db = HistoricalDatabase()

# Califa project data (key divisions from the real spreadsheet)
califa = (
    "Hard Cost Estimate\n\n"
    "\t\t\tHard Cost Estimate\n"
    "\t\t\t\t\tConstruction GBA\t43,683\tTotal Units\t76\n"
    "\t\t\t\t\tType 1 Area\t-\tType 3A Area\t43,683\n"
    "\t\t\t\t\t\tPer Unit\tPer GBA\tTotal\n"
    "\t\t\tDiv. 1 - GENERAL REQUIREMENTS\t\t$   16,851\t$   29.32\t$   1,280,698\n"
    "\t\t20-1000-1000\tField Supervision\t6%\t$   8,827\t$   15.36\t$   670,820\n"
    "\t\t20-4000-4000\tTrash Hauling - Dumpsters\t\t$   679\t$   1.18\t$   51,621\n"
    "\t\t20-9000-1000\tGR - Contractor Contingency 3%\t\t$   4,413\t$   7.68\t$   335,410\n"
    "\t\t\tDiv. 2 - OFF-SITE CONSTRUCTION\t\t$   485\t$   0.84\t$   36,872\n"
    "\t\t30-1000-1000\tCurbs - Gutters - Sidewalks\t\t$   485\t$   0.84\t$   36,872\n"
    "\t\t\tDiv. 2 - ON-SITE CONSTRUCTION\t\t$   3,370\t$   5.86\t$   256,082\n"
    "\t\t40-2000-1000\tEarthwork\t\t$   1,053\t$   1.83\t$   80,011\n"
    "\t\t40-5000-1000\tLandscaping and irrigation\t\t$   1,462\t$   2.54\t$   111,086\n"
    "\t\t\tDiv. 3 - CONCRETE\t\t$   5,007\t$   8.71\t$   380,531\n"
    "\t\t50-1000-3000\tConcrete Slab\t\t$   3,915\t$   6.81\t$   297,568\n"
    "\t\t50-1000-5000\tGypcrete\t\t$   1,092\t$   1.90\t$   82,963\n"
    "\t\t\tDiv. 4 - MASONRY\t\t$   207\t$   0.36\t$   15,726\n"
    "\t\t51-1000-4000\tVeneer Exterior - Material\t\t$   207\t$   0.36\t$   15,726\n"
    "\t\t\tDiv. 5 - METALS\t\t$   2,195\t$   3.82\t$   166,822\n"
    "\t\t52-1000-1000\tStructural Steel\t\t$   890\t$   1.55\t$   67,650\n"
    "\t\t52-1000-6000\tSheetmetal\t\t$   1,305\t$   2.27\t$   99,172\n"
    "\t\t\tDiv. 6 - WOOD AND PLASTICS\t\t$   31,737\t$   55.22\t$   2,411,998\n"
    "\t\t53-1000-1000\tFraming\t\t$   21,166\t$   36.83\t$   1,608,626\n"
    "\t\t53-1000-2000\tKitchen and Bath Cabinets\t\t$   3,500\t$   6.09\t$   266,000\n"
    "\t\t53-1000-3000\tKitchen and Bath Countertops\t\t$   1,350\t$   2.35\t$   102,600\n"
    "\t\t\tDiv. 7 - THERMAL & MOISTURE PROTECTION\t\t$   2,952\t$   5.14\t$   224,389\n"
    "\t\t54-1000-1000\tInsulation\t\t$   1,066\t$   1.86\t$   81,051\n"
    "\t\t54-1000-4000\tRoofing\t\t$   879\t$   1.53\t$   66,831\n"
    "\t\t\tDiv. 8 - DOORS, WINDOWS & GLAZING\t\t$   8,784\t$   15.28\t$   667,621\n"
    "\t\t55-1000-1000\tDoors and Hardware labor / materials\t\t$   4,955\t$   8.62\t$   376,558\n"
    "\t\t55-1000-4000\tWindows\t\t$   3,138\t$   5.46\t$   238,481\n"
    "\t\t\tDiv. 9 - FINISHES\t\t$   19,042\t$   33.13\t$   1,447,168\n"
    "\t\t56-1000-1000\tLath and Plaster\t\t$   3,925\t$   6.83\t$   298,312\n"
    "\t\t56-1000-2000\tDrywall\t\t$   11,068\t$   19.26\t$   841,148\n"
    "\t\t56-1000-5000\tPainting\t\t$   2,775\t$   4.83\t$   210,918\n"
    "\t\t\tDiv. 10 - SPECIALTIES\t\t$   890\t$   1.55\t$   67,667\n"
    "\t\t57-1000-1000\tBathroom Accessories\t\t$   231\t$   0.40\t$   17,556\n"
    "\t\t\tDiv. 11 - EQUIPMENT\t\t$   2,500\t$   4.35\t$   190,000\n"
    "\t\t58-1000-1000\tAppliances\t\t$   2,500\t$   5.98\t$   190,000\n"
    "\t\t\tDiv. 12 - FURNISHINGS\t\t$   289\t$   0.50\t$   21,980\n"
    "\t\t59-1000-2000\tWindow Coverings\t\t$   289\t$   0.50\t$   21,980\n"
    "\t\t\tDiv. 13 - SPECIAL CONSTRUCTION\t\t$   0\t$   0\t$   0\n"
    "\t\t\tDiv. 14 - CONVEYING SYSTEMS\t\t$   8,165\t$   14.21\t$   620,556\n"
    "\t\t61-1000-2000\tConstruction Elevator\t\t$   4,605\t$   8.01\t$   350,000\n"
    "\t\t61-1000-4000\tElevator\t\t$   3,289\t$   5.72\t$   250,000\n"
    "\t\t\tDiv. 15 - MECHANICAL\t\t$   31,985\t$   55.65\t$   2,430,845\n"
    "\t\t62-1000-1000\tHVAC Equipment\t\t$   8,500\t$   14.79\t$   646,000\n"
    "\t\t62-1000-2000\tRough Plumbing\t\t$   17,000\t$   29.58\t$   1,292,000\n"
    "\t\t\tDiv. 16 - ELECTRICAL\t\t$   21,476\t$   37.36\t$   1,632,190\n"
    "\t\t63-1000-1000\tElectrical\t\t$   17,000\t$   29.58\t$   1,292,000\n"
    "\t\t63-1000-8000\tLight Fixtures\t\t$   1,516\t$   2.64\t$   115,226\n"
    "\t\t\tPROJECT ADMINISTRATION\t\t$   13,240\t$   23.03\t$   1,006,229\n"
    "\t\t75-1000-1000\tGC Fee\t6%\t$   8,827\t$   15.36\t$   670,820\n"
    "\t\t75-1000-2000\tBonding\t1%\t$   1,471\t$   2.56\t$   111,803\n"
    "\t\t75-1000-3000\tAdministration\t2%\t$   2,942\t$   5.12\t$   223,607\n"
    "\nTarget Property\n\n"
    "\t\t\tAddress\t11218 Califia\n"
    "\t\t\tLot Size\t14,000\n"
    "\t\t\tTotal Pro-forma GBA\t\t43,683\n"
    "\t\t\tTotal Pro-forma GBA concrete\t\t0\n"
    "\t\t\tTotal Pro-forma GBA wood\t\t43,683\n"
    "\t\t\tTotal Units\t\t76\n"
    "\t\t\tStudio\t\t0\n"
    "\t\t\t1BR\t\t46\n"
    "\t\t\t2BR\t\t30\n"
)

# Whipple project data
whipple = (
    "Hard Cost Estimate\n\n"
    "\t\t\tHard Cost Estimate\n"
    "\t\t\t\t\tConstruction GBA\t54,230\tTotal Units\t91\n"
    "\t\t\t\t\tType 1 Area\t-\tType 3A Area\t54,230\n"
    "\t\t\t\t\t\tPer Unit\tPer GBA\tTotal\n"
    "\t\t\tDiv. 1 - GENERAL REQUIREMENTS\t\t$   15,826\t$   26.56\t$   1,440,182\n"
    "\t\t20-1000-1000\tField Supervision\t6%\t$   8,236\t$   13.82\t$   749,445\n"
    "\t\t20-4000-4000\tTrash Hauling - Dumpsters\t\t$   704\t$   1.18\t$   64,085\n"
    "\t\t20-9000-1000\tGR - Contractor Contingency 3%\t\t$   3,846\t$   6.45\t$   350,000\n"
    "\t\t\tDiv. 2 - OFF-SITE CONSTRUCTION\t\t$   503\t$   0.84\t$   45,775\n"
    "\t\t30-1000-1000\tCurbs - Gutters - Sidewalks\t\t$   503\t$   0.84\t$   45,775\n"
    "\t\t\tDiv. 2 - ON-SITE CONSTRUCTION\t\t$   4,113\t$   6.90\t$   374,273\n"
    "\t\t40-2000-1000\tEarthwork\t\t$   1,092\t$   1.83\t$   99,330\n"
    "\t\t40-5000-1000\tLandscaping and irrigation\t\t$   1,099\t$   2.54\t$   100,000\n"
    "\t\t\tDiv. 3 - CONCRETE\t\t$   5,155\t$   8.65\t$   469,105\n"
    "\t\t50-1000-3000\tConcrete Slab\t\t$   4,023\t$   6.75\t$   366,112\n"
    "\t\t50-1000-5000\tGypcrete\t\t$   1,132\t$   1.90\t$   102,993\n"
    "\t\t\tDiv. 4 - MASONRY\t\t$   215\t$   0.36\t$   19,523\n"
    "\t\t51-1000-4000\tVeneer Exterior - Material\t\t$   215\t$   0.36\t$   19,523\n"
    "\t\t\tDiv. 5 - METALS\t\t$   2,276\t$   3.82\t$   207,100\n"
    "\t\t52-1000-1000\tStructural Steel\t\t$   923\t$   1.55\t$   83,984\n"
    "\t\t52-1000-6000\tSheetmetal\t\t$   1,353\t$   2.27\t$   123,117\n"
    "\t\t\tDiv. 6 - WOOD AND PLASTICS\t\t$   30,284\t$   50.82\t$   2,755,824\n"
    "\t\t53-1000-1000\tFraming\t\t$   21,945\t$   36.83\t$   1,997,020\n"
    "\t\t53-1000-2000\tKitchen and Bath Cabinets\t\t$   3,500\t$   5.87\t$   318,500\n"
    "\t\t53-1000-3000\tKitchen and Bath Countertops\t\t$   1,350\t$   2.27\t$   122,850\n"
    "\t\t\tDiv. 7 - THERMAL & MOISTURE PROTECTION\t\t$   3,061\t$   5.14\t$   278,567\n"
    "\t\t54-1000-1000\tInsulation\t\t$   1,106\t$   1.86\t$   100,620\n"
    "\t\t54-1000-4000\tRoofing\t\t$   912\t$   1.53\t$   82,967\n"
    "\t\t\tDiv. 8 - DOORS, WINDOWS & GLAZING\t\t$   9,108\t$   15.28\t$   828,814\n"
    "\t\t55-1000-1000\tDoors and Hardware labor / materials\t\t$   5,137\t$   8.62\t$   467,475\n"
    "\t\t55-1000-4000\tWindows\t\t$   3,253\t$   5.46\t$   296,061\n"
    "\t\t\tDiv. 9 - FINISHES\t\t$   19,743\t$   33.13\t$   1,796,578\n"
    "\t\t56-1000-1000\tLath and Plaster\t\t$   4,070\t$   6.83\t$   370,338\n"
    "\t\t56-1000-2000\tDrywall\t\t$   11,475\t$   19.26\t$   1,044,238\n"
    "\t\t56-1000-5000\tPainting\t\t$   2,877\t$   4.83\t$   261,843\n"
    "\t\t\tDiv. 10 - SPECIALTIES\t\t$   923\t$   1.55\t$   84,005\n"
    "\t\t57-1000-1000\tBathroom Accessories\t\t$   240\t$   0.40\t$   21,795\n"
    "\t\t\tDiv. 11 - EQUIPMENT\t\t$   2,372\t$   3.98\t$   215,820\n"
    "\t\t58-1000-1000\tAppliances\t\t$   2,372\t$   3.98\t$   215,820\n"
    "\t\t\tDiv. 12 - FURNISHINGS\t\t$   300\t$   0.50\t$   27,288\n"
    "\t\t59-1000-2000\tWindow Coverings\t\t$   300\t$   0.50\t$   27,288\n"
    "\t\t\tDiv. 13 - SPECIAL CONSTRUCTION\t\t$   1,099\t$   1.84\t$   100,000\n"
    "\t\t60-1000-1000\tSolar Systems\t\t$   1,099\t$   1.84\t$   100,000\n"
    "\t\t\tDiv. 14 - CONVEYING SYSTEMS\t\t$   4,291\t$   7.20\t$   390,519\n"
    "\t\t61-1000-2000\tConstruction Elevator\t\t$   1,593\t$   2.67\t$   145,000\n"
    "\t\t61-1000-4000\tElevator\t\t$   1,758\t$   2.95\t$   160,000\n"
    "\t\t\tDiv. 15 - MECHANICAL\t\t$   26,808\t$   44.98\t$   2,439,500\n"
    "\t\t62-1000-1000\tHVAC Equipment\t\t$   8,500\t$   14.26\t$   773,500\n"
    "\t\t62-1000-2000\tRough Plumbing\t\t$   13,297\t$   22.28\t$   1,210,000\n"
    "\t\t\tDiv. 16 - ELECTRICAL\t\t$   19,421\t$   32.59\t$   1,767,326\n"
    "\t\t63-1000-1000\tElectrical\t\t$   14,780\t$   24.80\t$   1,345,000\n"
    "\t\t63-1000-8000\tLight Fixtures\t\t$   1,572\t$   2.64\t$   143,046\n"
    "\t\t\tPROJECT ADMINISTRATION\t\t$   13,040\t$   21.88\t$   1,186,621\n"
    "\t\t75-1000-1000\tGC Fee\t6%\t$   8,236\t$   13.82\t$   749,445\n"
    "\t\t75-1000-2000\tBonding\t1.5%\t$   2,059\t$   3.45\t$   187,361\n"
    "\t\t75-1000-3000\tAdministration\t2%\t$   2,745\t$   4.61\t$   249,815\n"
    "\nTarget Property\n\n"
    "\t\t\tAddress\t10953 Whipple\n"
    "\t\t\tLot Size\t17,982\n"
    "\t\t\tTotal Pro-forma GBA\t\t54,230\n"
    "\t\t\tTotal Pro-forma GBA concrete\t\t0\n"
    "\t\t\tTotal Pro-forma GBA wood\t\t54,230\n"
    "\t\t\tTotal Units\t\t91\n"
    "\t\t\tStudio\t\t0\n"
    "\t\t\t1BR\t\t64\n"
    "\t\t\t2BR\t\t27\n"
)

# Load both projects
p1 = db.add_project_from_text(califa, "Califa.xlsx", "1954903405342")
p2 = db.add_project_from_text(whipple, "Whipple.xlsx", "1954910334245")

print(f"Loaded {db.project_count} projects")
print(f"  {p1.name}: {p1.gba:,.0f} SF, {p1.total_units} units, ${p1.cost_per_sf:,.0f}/SF")
print(f"  {p2.name}: {p2.gba:,.0f} SF, {p2.total_units} units, ${p2.cost_per_sf:,.0f}/SF")
print(f"  Cost codes tracked: {len(db.get_all_cost_codes())}")
print()

# Generate estimate for a new 50,000 SF project
engine = EstimatorEngine(db)
estimate = engine.estimate(
    gba=50000,
    units=85,
    unit_mix={"1BR": 55, "2BR": 30},
    construction_type="wood",
    num_floors=5,
)
print(estimate.summary())

# Save database
db.save("construction_estimator/historical_data.json")
print("\nDatabase saved to construction_estimator/historical_data.json")
