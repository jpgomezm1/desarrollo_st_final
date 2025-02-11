# mass_processor.py

import openpyxl

def process_excel_file(excel_path):
    """
    Lee un archivo Excel y retorna una lista de URLs encontradas en la columna A
    (desde la fila 1 hasta donde haya datos).
    
    Args:
        excel_path (str): Ruta al archivo de Excel.
        
    Returns:
        List[str]: Lista de URLs leídas.
    """
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb.active
        urls = []
        for row in ws.iter_rows(min_row=1, max_col=1, values_only=True):
            cell_value = row[0]
            if cell_value and isinstance(cell_value, str):
                urls.append(cell_value.strip())
        return urls
    except Exception as e:
        print(f"Error leyendo archivo Excel: {e}")
        return []
