class Scenarios:
    def __init__(self, code, description, sale_type):
        self.code = code
        self.description = description
        self.sale_type = sale_type

scenario_list = [
    Scenarios(
        "SN001",
        "Goods at standard rate to registered buyers",
        "Goods at standard rate (default)",
    ),
    Scenarios(
        "SN002",
        "Goods at standard rate to unregistered buyers",
        "Goods at standard rate (default)",
    ),
    Scenarios(
        "SN003", "Sale of Steel (Melted and Re-Rolled)", "Steel Melting and re-rolling"
    ),
    Scenarios("SN004", "Sale by Ship Breakers", "Ship breaking"),
    Scenarios("SN005", "Reduced rate sale", "Goods at Reduced Rate"),
    Scenarios("SN006", "Exempt goods sale", "Exempt goods"),
    Scenarios("SN007", "Zero rated sale", "Goods at zero-rate"),
    Scenarios("SN008", "Sale of 3rd schedule goods", "3rd Schedule Goods"),
    Scenarios(
        "SN009",
        "Cotton Spinners purchase from Cotton Ginners (Textile Sector)",
        "Cotton ginners",
    ),
    Scenarios(
        "SN010",
        "Mobile Operators adds Sale (Telecom Sector)",
        "Telecommunication services",
    ),
    Scenarios("SN011", "Toll Manufacturing sale by Steel sector", "Toll Manufacturing"),
    Scenarios("SN012", "Sale of Petroleum products", "Petroleum Products"),
    Scenarios(
        "SN013", "Electricity Supply to Retailers", "Electricity Supply to Retailers"
    ),
    Scenarios("SN014", "Sale of Gas to CNG stations", "Gas to CNG stations"),
    Scenarios("SN015", "Sale of mobile phones", "Mobile phones"),
    Scenarios(
        "SN016", "Processing / Conversion of Goods", "Processing/Conversion of Goods"
    ),
    Scenarios(
        "SN017",
        "Sale of Goods where FED is charged in ST mode",
        "Goods (FED in ST Mode)",
    ),
    Scenarios(
        "SN018",
        "Sale of Services where FED is charged in ST mode",
        "Services (FED in ST Mode)",
    ),
    Scenarios("SN019", "Sale of Services", "Services"),
    Scenarios("SN020", "Sale of Electric Vehicles", "Electric Vehicle"),
    Scenarios("SN021", "Sale of Cement /Concrete Block", "Cement /Concrete Block"),
    Scenarios("SN022", "Sale of Potassium Chlorate", "Potassium chlorate"),
    Scenarios("SN023", "Sale of CNG", "CNG Sales"),
    Scenarios(
        "SN024",
        "Goods sold that are listed in SRO 297(1)/2023",
        "Goods as per SRO.297(|)/2023",
    ),
    Scenarios(
        "SN025",
        "Drugs sold at fixed ST rate under serial 81 of Eighth Schedule Table 1",
        "Non-Adjustable Supplies",
    ),
    Scenarios(
        "SN026", "Sale to End Consumer by retailers", "Goods at standard rate (default)"
    ),
    Scenarios("SN027", "Sale to End Consumer by retailers", "3rd Schedule Goods"),
    Scenarios("SN028", "Sale to End Consumer by retailers", "Goods at Reduced Rate"),
]
