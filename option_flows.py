import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.colors as mcolors

class HeatMap:
    """
    HeatMap class for visualizing option trade flows of an asset on Deribit.
    """
    def __init__(self, asset, lookback_hours):
        """
        Initializes the HeatMap class with the specified asset and lookback period.
        
        :param asset: The asset for which to generate the heatmap (BTC or ETH)
        :param lookback_hours: The number of hours to look back for trades
        """
        self.asset = asset.upper()
        self.lookback_hours = lookback_hours

    def _get_unix_timestamp(self, dt):
        """
        Converts a datetime object to a Unix timestamp in milliseconds.
        
        :param dt: Datetime object to convert
        :return: Unix timestamp in milliseconds
        """
        return int(dt.timestamp() * 1000)

    def _get_url(self, end_timestamp):
        """
        Constructs the API URL for fetching trade data.
        
        :param end_timestamp: Unix timestamp marking the end of the period for fetching trades
        :return: Constructed URL for the API request
        """
        url_template = ("https://history.deribit.com/api/v2/public/get_last_trades_by_currency?"
                        "currency={}&include_old=True&count=10000&kind=option&end_timestamp={}")
        return url_template.format(self.asset, end_timestamp)
    
    def _get_current_price(self):
        """
        Fetches the current index price of the asset.
        
        :return: Current index price of the asset
        """
        url = 'https://deribit.com/api/v2/public/get_index_price?index_name='+str(self.asset.lower()) + '_usd'
        x =  requests.get(url).json()
        return float(x['result']['index_price'])

    def get_data(self):
        """
        Fetches and stores trade data from the API.
        
        :return: DataFrame containing the fetched trade data
        """        
        collected_data = []  # List to store dataframes of fetched trades
        
        end_datetime = datetime.utcnow()
        start_datetime = end_datetime - timedelta(hours=self.lookback_hours)  
        current_datetime = end_datetime
        start_timestamp_unix = self._get_unix_timestamp(start_datetime)
        end_timestamp_unix = self._get_unix_timestamp(end_datetime)

        # Loop to fetch trades in chunks until the start of the lookback period is reached
        while current_datetime >= start_datetime:                        
            # Use end timestamp or the timestamp of the last fetched trade for the next API call
            api_timestamp = end_timestamp_unix if not collected_data else self._get_unix_timestamp(current_datetime)
            api_url = self._get_url(api_timestamp)

            response = requests.get(api_url)
            trades_data = response.json().get('result', {}).get('trades', [])
            
            if not trades_data:
                print("No more trades to fetch.")
                break

            # Get timestamp of the last trade to update `current_datetime`
            last_trade_unix_timestamp = trades_data[-1]['timestamp']
            current_datetime = pd.to_datetime(last_trade_unix_timestamp, unit='ms')

            # Convert the trades to a DataFrame, convert timestamp to datetime, and store it
            df_trades = pd.DataFrame(trades_data)
            df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'], unit='ms')
            collected_data.append(df_trades)
            
        # Concatenate all collected DataFrames into one
        combined_data = pd.concat(collected_data)
        combined_data.reset_index(drop=True, inplace=True)
        combined_data.drop_duplicates(subset='trade_id', keep="last", inplace=True)

        # Filter trades to the lookback period and sort by timestamp
        filtered_data = combined_data[(combined_data['timestamp'] >= start_datetime) & (combined_data['timestamp'] <= end_datetime)]
        sorted_data = filtered_data.sort_values(by='timestamp')

        return sorted_data
    
    def clean_data(self, data):
        """
        Cleans and prepares the data for plotting.
        
        :param data: DataFrame containing the trade data
        :return: DataFrame with the required subset of cleaned trade data
        """
        # Split instrument_name into its components
        instrument_components = data['instrument_name'].str.split("-", expand=True)
        instrument_components.columns = ['underlying', 'maturity', 'strike', 'op_type']

        # Convert maturity to datetime and strike to integer
        instrument_components['maturity'] = pd.to_datetime(instrument_components['maturity'])
        instrument_components['strike'] = instrument_components['strike'].astype(float).astype(int)

        # Merge the split instrument components back into the original dataframe
        merged_data = pd.concat([data, instrument_components], axis=1)

        # Convert 'direction' to numerical values and calculate 'net_amount'
        merged_data['direction'] = np.where(merged_data['direction'] == 'sell', -1, 1)
        merged_data['net_amount'] = merged_data['direction'] * merged_data['amount']

        # Fill NaN in 'block_trade_id' and create 'block_trades' indicator
        merged_data['block_trade_id'] = merged_data['block_trade_id'].fillna('NAN')
        merged_data['block_trades'] = np.where(merged_data['block_trade_id'] != 'NAN', 1, 0)
    
        # Sort by 'maturity' and reset index
        sorted_data = merged_data.sort_values("maturity").reset_index(drop=True)
        
        # Filter for only block trades
        sorted_data = sorted_data[sorted_data.block_trades==1].reset_index(drop=True)

        # Return the specified subset of the dataframe
        return sorted_data[['timestamp', 'maturity', 'strike', 'net_amount']]    
    
    def plot_data(self):
        """
        Plots the heatmap using the cleaned trade data.
        """
        cleaned_data = self.clean_data(self.get_data())             

        # Define the start and end times for the title
        start_time = cleaned_data.timestamp.min().strftime("%Y-%m-%d %H:%M")
        end_time = cleaned_data.timestamp.max().strftime("%Y-%m-%d %H:%M")

        # Create a pivot table for the heatmap data
        heatmap_data = pd.pivot_table(
            cleaned_data,
            values='net_amount',
            index=['maturity'],
            columns=['strike'],
            aggfunc=np.sum
        )
        
        # Format the maturity dates for display
        heatmap_data.index = heatmap_data.index.strftime("%y-%b-%d")

        # Initialize the figure and axis
        plt.figure(figsize=(50, 40))    
        
        # Create custom cmap for heatmap
        colors = ["red", "white", "green"] 
        cmap = LinearSegmentedColormap.from_list("custom_cmap", colors)
        
        # Find the maximum absolute value for symmetric coloring
        max_abs_value = np.max(np.abs(heatmap_data.fillna(0).to_numpy().flatten()))
        # Create a diverging colormap that is centered on zero
        diverging_cmap = mcolors.TwoSlopeNorm(vmin=-max_abs_value, vcenter=0, vmax=max_abs_value)        

        # Generate the heatmap
        ax = sns.heatmap(
            heatmap_data,
            cmap=cmap, 
            norm=diverging_cmap,
            robust=True,
            linewidths=0.50,            
            linecolor='grey',
            rasterized=False,
            fmt=".1f",
            cbar=True,
            cbar_kws={
                "orientation": "horizontal",
                "pad": 0.1,
                'shrink': 0.75
            },
            square=False,
            annot=True,
            annot_kws={"fontsize":25, "color":'black'}
        )

        # Set the heatmap color limits
        ax.collections[0].set_clim(heatmap_data.min().min(), heatmap_data.max().max())
        
        # Set borders
        ax.hlines(y=ax.get_ylim()[0], xmin=ax.get_xlim()[0], xmax=ax.get_xlim()[1], colors='grey', linestyles='solid', linewidth=2)
        ax.vlines(x=ax.get_xlim()[1], ymin=ax.get_ylim()[0], ymax=ax.get_ylim()[1], colors='grey', linestyles='solid', linewidth=2)

        # Customize the colorbar
        cbar = ax.collections[0].colorbar
        cbar.ax.tick_params(labelsize=45)
        cbar.set_label("Net Contracts Traded", size=45, labelpad=30)

        # Adjust axis labels, ticks, and title
        plt.xticks(rotation=90, fontsize=45)
        # Rotation set to 0 for readability
        plt.yticks(rotation=0, fontsize=45)  
        plt.xlabel("Strike", fontsize=45, labelpad=20)
        plt.ylabel("Maturity", fontsize=45, labelpad=50)

        # Title with dynamic asset name and time range
        plt.title(f"{self.asset} Deribit Option Block Trade Flows: {start_time} - {end_time} UTC",
                  fontsize=50, pad=40)

        # Highlight the current price line
        current_price = self._get_current_price()
        closest_strike_location = min(
            range(len(heatmap_data.columns)),
            key=lambda i: abs(heatmap_data.columns[i] - current_price)
        )
        plt.axvline(closest_strike_location, linewidth=10, c='blue', linestyle='--')

        # Final layout settings and save the figure
        plt.tight_layout()
        filename = f"{self.asset}_deribit_block_flows_{start_time}_{end_time}.png"
        plt.savefig(filename, bbox_inches='tight', pad_inches=2, facecolor='white')