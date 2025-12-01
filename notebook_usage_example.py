# This is an example of how to use the market_chart_tv module in a Jupyter Notebook.
# You would copy the code below into a cell in your notebook.

from IPython.display import HTML
import sys
import os

# Ensure the script is in the python path
sys.path.append(os.getcwd())

# Import the helper function
from market_chart_tv import get_notebook_chart

# Generate and display the chart
# This fetches fresh data and renders the interactive chart inline
html_content = get_notebook_chart(period="7d", interval="1m")

# Display it
HTML(html_content)
