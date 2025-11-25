import dash
from dash import dcc, html, Input, Output
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta

# ==========================================
# PART 1: CONFIGURATION
# ==========================================

ANALYTICS_DB = 'analytics.db'
MAIN_DB = 'database.db'

# DATA PRIVACY SETTINGS
# Set to False to anonymize names in the dashboard (e.g., "User 101")
SHOW_REAL_NAMES = False 

EXCLUDED_USER_ID = 23  # None or id of dev who's been viewing a lot and skewing results

# ==========================================
# PART 2: DATA LOADING & PROCESSING
# ==========================================

def get_db_connection(db_file):
    if not os.path.exists(db_file):
        return None
    try:
        return sqlite3.connect(db_file)
    except Exception:
        return None

def load_data():
    """
    Loads data, separates Creations (v1) from Edits (v>1), 
    and processes Analytics.
    """
    conn_main = get_db_connection(MAIN_DB)
    conn_analytics = get_db_connection(ANALYTICS_DB)

    if not conn_main or not conn_analytics:
        print("Error: Database files not found.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    try:
        # 1. Load Content (All Versions) to distinguish Creations vs Edits
        # Note: We query all versions now, not just version=1
        q_init = "SELECT id, 'initiatives' as type, responsible_person, created_by, version, CAST(timestamp AS TEXT) as timestamp FROM initiatives"
        q_cont = "SELECT id, 'contracts' as type, responsible_person, created_by, version, CAST(timestamp AS TEXT) as timestamp FROM contracts"
        q_act = "SELECT id, 'activities' as type, NULL as responsible_person, created_by, version, CAST(timestamp AS TEXT) as timestamp FROM activities"

        df_init = pd.read_sql(q_init, conn_main)
        df_cont = pd.read_sql(q_cont, conn_main)
        df_act = pd.read_sql(q_act, conn_main)
        
        # Load People
        df_people = pd.read_sql("SELECT id, name FROM people", conn_main)
        
        # Load Analytics
        df_analytics_raw = pd.read_sql("SELECT id, person_id, requested_table, requested_id, CAST(timestamp AS TEXT) as timestamp FROM analytics", conn_analytics)
        
        if EXCLUDED_USER_ID is not None:
            df_analytics_raw = df_analytics_raw[df_analytics_raw['person_id'] != EXCLUDED_USER_ID]

    except Exception as e:
        print(f"Error reading databases: {e}")
        conn_main.close()
        conn_analytics.close()
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    conn_main.close()
    conn_analytics.close()

    # --- PROCESSING ---

    # 1. Anonymization Logic
    if not SHOW_REAL_NAMES:
        df_people['name'] = "User " + df_people['id'].astype(str)

    # 2. Process Content (Creations vs Edits)
    df_content_all = pd.concat([df_init, df_cont, df_act], ignore_index=True)
    df_content_all['timestamp'] = pd.to_datetime(df_content_all['timestamp'], format='ISO8601')

    # Split: Version 1 = Creation, Version > 1 = Edit
    df_creations = df_content_all[df_content_all['version'] == 1].copy()
    df_edits = df_content_all[df_content_all['version'] > 1].copy()

    # 3. Process Analytics
    if df_analytics_raw.empty:
        df_analytics_enriched = pd.DataFrame()
    else:
        df_analytics_raw['timestamp'] = pd.to_datetime(df_analytics_raw['timestamp'], format='ISO8601')
        
        # Merge with User Names
        df_analytics_enriched = df_analytics_raw.merge(
            df_people[['id', 'name']], 
            left_on='person_id', 
            right_on='id', 
            how='left'
        )
        df_analytics_enriched.rename(columns={'name': 'user_name'}, inplace=True)
        df_analytics_enriched['user_name'].fillna('Unknown', inplace=True)

        # 4. "Self vs Collaboration" Logic
        # Create a lookup reference for ownership. 
        # We use the LATEST version of content to determine current responsibility.
        df_latest_content = df_content_all.sort_values('version').drop_duplicates(['id', 'type'], keep='last')

        def determine_type(row):
            # Find the item in our content DB
            item = df_latest_content[
                (df_latest_content['id'] == row['requested_id']) & 
                (df_latest_content['type'] == row['requested_table'])
            ]
            
            if item.empty:
                return "Unknown Content"

            viewer = row['person_id']
            creator = item.iloc[0]['created_by']
            owner = item.iloc[0]['responsible_person'] # Nan for activities

            # Logic: If you created it OR you are currently responsible -> Self
            if (viewer == creator) or (viewer == owner):
                return "Self (Own Work)"
            
            return "Collaboration"

        df_analytics_enriched['interaction_type'] = df_analytics_enriched.apply(determine_type, axis=1)

    return df_analytics_enriched, df_creations, df_edits

# ==========================================
# PART 3: DASH APP
# ==========================================

df_analytics, df_creations, df_edits = load_data()

app = dash.Dash(__name__, external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])
app.title = "Collaboratorium Analytics"

# Date Range Defaults
if not df_analytics.empty:
    min_date = min(df_analytics['timestamp'].min(), df_creations['timestamp'].min())
    max_date = datetime.now()
else:
    min_date = datetime.now() - timedelta(days=30)
    max_date = datetime.now()

app.layout = html.Div([
    html.H1("Collaboratorium Usage Analytics", style={'textAlign': 'center', 'color': '#2c3e50'}),
    
    # --- Date Filter ---
    html.Div([
        html.Label("Filter Time Period:"),
        dcc.DatePickerRange(
            id='date-picker-range',
            start_date=min_date,
            end_date=max_date,
            display_format='YYYY-MM-DD'
        )
    ], style={'textAlign': 'center', 'marginBottom': '30px'}),

    # --- Top Metrics Row ---
    html.Div([
        html.Div([
            html.H4(id='metric-views'),
            html.P("Total Views")
        ], className='two columns', style={'backgroundColor': '#f9f9f9', 'padding': '20px', 'borderRadius': '5px', 'textAlign': 'center'}),
        
        html.Div([
            html.H4(id='metric-creations'),
            html.P("New Items")
        ], className='two columns', style={'backgroundColor': '#f9f9f9', 'padding': '20px', 'borderRadius': '5px', 'textAlign': 'center'}),

        html.Div([
            html.H4(id='metric-edits'),
            html.P("Edits / Updates")
        ], className='two columns', style={'backgroundColor': '#f9f9f9', 'padding': '20px', 'borderRadius': '5px', 'textAlign': 'center'}),
        
        html.Div([
            html.H4(id='metric-users'),
            html.P("Active Users")
        ], className='two columns', style={'backgroundColor': '#e8f4f8', 'padding': '20px', 'borderRadius': '5px', 'textAlign': 'center'}),
        
        html.Div([
            html.H4(id='metric-collab'),
            html.P("Collab Rate")
        ], className='two columns', style={'backgroundColor': '#fff9c4', 'padding': '20px', 'borderRadius': '5px', 'textAlign': 'center'}),
    ], className='row', style={'justifyContent': 'center', 'marginBottom': '30px'}),

    # --- Timeline ---
    html.Div([
        html.H5("Activity Timeline", style={'textAlign': 'center'}),
        dcc.Graph(id='timeline-graph')
    ], className='row', style={'marginBottom': '20px'}),

    # --- Row 2: Collab & Volume ---
    html.Div([
        html.Div([
            html.H5("Work Styles (Self vs Collaboration)"),
            dcc.Graph(id='collab-graph')
        ], className='six columns'),

        html.Div([
            html.H5("User Activity Volume"), # Renamed from Leaderboard
            dcc.Graph(id='volume-graph')
        ], className='six columns'),
    ], className='row'),

    # --- Row 3: Content Type ---
    html.Div([
         html.Div([
            html.H5("Content Popularity"),
            dcc.Graph(id='pie-graph')
        ], className='six columns', style={'margin': '0 auto', 'float': 'none'}),
    ], className='row')

], style={'maxWidth': '1200px', 'margin': '0 auto', 'padding': '20px'})

# ==========================================
# PART 4: CALLBACKS
# ==========================================

@app.callback(
    [Output('timeline-graph', 'figure'),
     Output('collab-graph', 'figure'),
     Output('volume-graph', 'figure'),
     Output('pie-graph', 'figure'),
     Output('metric-views', 'children'),
     Output('metric-creations', 'children'),
     Output('metric-edits', 'children'),
     Output('metric-users', 'children'),
     Output('metric-collab', 'children')],
    [Input('date-picker-range', 'start_date'),
     Input('date-picker-range', 'end_date')]
)
def update_dashboard(start_date, end_date):
    # Empty state handling
    if df_analytics.empty and df_creations.empty:
        return go.Figure(), go.Figure(), go.Figure(), go.Figure(), "0", "0", "0", "0", "0%"

    # Filter Dataframes
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    sub_analytics = df_analytics[(df_analytics['timestamp'] >= start) & (df_analytics['timestamp'] <= end)]
    sub_creations = df_creations[(df_creations['timestamp'] >= start) & (df_creations['timestamp'] <= end)]
    sub_edits = df_edits[(df_edits['timestamp'] >= start) & (df_edits['timestamp'] <= end)]

    # --- Metrics ---
    count_views = len(sub_analytics)
    count_creations = len(sub_creations)
    count_edits = len(sub_edits)
    count_users = sub_analytics['person_id'].nunique()
    
    collab_only = sub_analytics[sub_analytics['interaction_type'] == 'Collaboration']
    collab_rate = (len(collab_only) / count_views * 100) if count_views > 0 else 0

    # --- Graph 1: Timeline (Multi-line) ---
    # We create a dataframe for the timeline by resampling all 3 datasets
    tl_views = sub_analytics.set_index('timestamp').resample('D').size().reset_index(name='Count')
    tl_views['Category'] = 'Views'
    
    tl_creates = sub_creations.set_index('timestamp').resample('D').size().reset_index(name='Count')
    tl_creates['Category'] = 'Creations'

    tl_edits = sub_edits.set_index('timestamp').resample('D').size().reset_index(name='Count')
    tl_edits['Category'] = 'Edits'

    df_timeline = pd.concat([tl_views, tl_creates, tl_edits])
    
    fig_timeline = px.line(df_timeline, x='timestamp', y='Count', color='Category',
                           color_discrete_map={
                               'Views': '#3498db',     # Blue
                               'Creations': '#2ecc71', # Green
                               'Edits': '#f39c12'      # Orange
                           }, template='plotly_white')
    fig_timeline.update_layout(margin=dict(l=20, r=20, t=10, b=20))

    # --- Graph 2: Stacked Bar (Collab) ---
    if not sub_analytics.empty:
        df_stack = sub_analytics.groupby(['user_name', 'interaction_type']).size().reset_index(name='count')
        fig_collab = px.bar(df_stack, x='user_name', y='count', color='interaction_type',
                            color_discrete_map={'Self (Own Work)': '#95a5a6', 'Collaboration': '#9b59b6'},
                            template='plotly_white')
        fig_collab.update_layout(xaxis_title=None, yaxis_title="Interactions", legend_title=None)
    else:
        fig_collab = go.Figure()

    # --- Graph 3: Activity Volume (Previously Leaderboard) ---
    if not sub_analytics.empty:
        # Simple count of interactions per user
        df_vol = sub_analytics['user_name'].value_counts().reset_index()
        df_vol.columns = ['user_name', 'count']
        # We sort by name alphabetically or just by count, but without labeling it "Rank"
        fig_vol = px.bar(df_vol, x='user_name', y='count', template='plotly_white',
                         color_discrete_sequence=['#5c6bc0'])
        fig_vol.update_layout(xaxis_title=None, yaxis_title="Total Activity")
    else:
        fig_vol = go.Figure()

    # --- Graph 4: Pie ---
    if not sub_analytics.empty:
        df_pie = sub_analytics['requested_table'].value_counts().reset_index()
        df_pie.columns = ['Type', 'count']
        fig_pie = px.pie(df_pie, values='count', names='Type', hole=0.4, 
                         color_discrete_sequence=px.colors.sequential.RdBu)
    else:
        fig_pie = go.Figure()

    return (fig_timeline, fig_collab, fig_vol, fig_pie, 
            f"{count_views:,}", f"{count_creations:,}", f"{count_edits:,}", 
            f"{count_users}", f"{collab_rate:.1f}%")

if __name__ == '__main__':
    app.run(debug=True)