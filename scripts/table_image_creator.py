import plotly.graph_objects as go
import numpy as np
import sys
import os
import base64
sys.path.append("./")
from scripts import utils


def save_matchday_table_as_image(table_data, season, matchday, league_name, config_path, filename, logo_path):
    config = utils.read_json(config_path)
    fig_height = 720
    fig_width = 720
    top_margin = 101

    colors = ['indianred', 'orange', 'gold', 'greenyellow', 'lightskyblue', 'slateblue']
    distribution = []
    for league in config["leagues"]:
        if league_name in league["names"]:
            distribution = league["distribution"]
            break
    if not distribution:
        raise ValueError(f"League '{league_name}' not found in config.")

    place_colors = {}
    place = 1
    for count, color in zip(distribution, colors):
        for _ in range(count):
            place_colors[place] = color
            place += 1

    headers = list(table_data[0].keys())
    columns = {h: [row[h] for row in table_data] for h in headers}
    n_rows = len(table_data)

    fill_colors = []
    font_colors = []

    for i in range(n_rows):
        row_bg = []
        row_font = []
        for j, header in enumerate(headers):
            if header == "Place":
                place_val = columns[header][i]
                color = place_colors.get(place_val, 'white')
                row_bg.append(color)
                row_font.append('black')
            elif header == "Points":
                row_bg.append('silver')
                row_font.append('black')
            else:
                row_bg.append('silver')
                row_font.append('black')
        fill_colors.append(row_bg)
        font_colors.append(row_font)

    fill_colors_t = list(map(list, zip(*fill_colors)))
    font_colors_t = list(map(list, zip(*font_colors)))

    # Adjusted column widths and alignments
    column_widths = []
    alignments = []
    display_headers = []

    for h in headers:
        h_lower = h.lower()
        if h_lower == "place":
            column_widths.append(40)
            display_headers.append("")
            alignments.append("center")
        elif h_lower == "manager":
            column_widths.append(400)
            display_headers.append(f"<b>{h}</b>")
            alignments.append("left")
        elif h_lower in ("md"):
            column_widths.append(60)
            display_headers.append(f"<b>{h}</b>")
            alignments.append("right")
        elif h_lower == "korr.":
            column_widths.append(70)
            display_headers.append(f"<b>{h}</b>")
            alignments.append("right")
        elif h_lower in ("points"):
            column_widths.append(100)
            display_headers.append(f"<b>{h}</b>")
            alignments.append("right")
        else:
            column_widths.append(80)
            display_headers.append(f"<b>{h}</b>")
            alignments.append("center")

    fig = go.Figure(data=[go.Table(
        columnwidth=column_widths,
        header=dict(
            values=display_headers,
            fill_color='firebrick',
            font=dict(color='white', size=20),
            align=alignments,
            height=40
        ),
        cells=dict(
            values=[columns[h] for h in headers],
            fill_color=fill_colors_t,
            font=dict(color=font_colors_t, size=19, family='Arial'),
            align=alignments,
            height=34,
        ))])

    fig.update_layout(
        width=fig_width,
        height=fig_height,
        margin=dict(l=0, r=0, t=top_margin, b=0),
        title=dict(
            text=f"{league_name}<br>{season} - Matchday {matchday}",
            x=0.5,
            xanchor='center',
            font=dict(size=26)
        ))

    if os.path.exists(logo_path):
        with open(logo_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode()

        factor = 1.1
        sizey = (top_margin / (fig_height)) * factor
        sizex = sizey

        fig.update_layout(
            images=[dict(
                source=f"data:image/png;base64,{encoded_image}",
                xref="paper", yref="paper",
                x=0 + sizex*0.025, y=1 + sizey*1.025,
                sizex=sizex, sizey=sizey,
                xanchor="left", yanchor="top",
                layer="above"
        )])
    else:
        print(f"⚠️ Logo file not found at: {logo_path}. Skipping logo overlay.")

    fig.write_image(filename + '.jpeg', format="jpeg", scale=2)
    print(f"💾 Saved table as {filename}")



def save_kblscore_table_as_image(system, tablelist, seasons, filename):
        seasons_cut = [s[-3:] for s in seasons]
        header = [system.upper(), "Name", "Liga"] + seasons_cut + ["KBL Score"]
        colors = ['silver']
        factor = [1]
        colorlist = sum([[s] * n for s, n in zip(colors, factor)], [])
        columnwid = [14, 40, 23] + [13]*5 + [24]*(len(seasons)-5) + [16]
        image_width = len(seasons) * 25 + 300
        image_height = 23.3 * len(tablelist)

        layout = go.Layout(
        margin=go.layout.Margin(
            l=0,
            r=0,
            b=0,
            t=0
        ))

        nicetable = go.Figure(data=[go.Table(
        columnwidth=columnwid,
        header=dict(values=header,
                    fill_color='firebrick',
                    align='center',
                    font=dict(color='white')),
        cells=dict(values=np.transpose(tablelist),
                   fill=dict(color=[colorlist, 'silver']),
                   height=22,
                   font_size=11,
                   align=['center', 'left', 'left'] + ['right']*len(seasons) + ['right']),
        )],layout=layout)

        nicetable.write_image(filename + ".jpeg", width=image_width, height=image_height)  # früher 23.4
        print(f"💾 KBL Score Table written to {filename}.")


def save_alltime_table_as_image(filename, tablelist, header, columnwid):
        colors = ['silver']
        factor = [1]
        colorlist = sum([[s] * n for s, n in zip(colors, factor)], [])
        image_width = 720
        image_height = 45 + 22 * len(tablelist)

        layout = go.Layout(
        margin=go.layout.Margin(
            l=0,
            r=0,
            b=0,
            t=0
        ))

        nicetable = go.Figure(data=[go.Table(
        columnwidth=columnwid,
        header=dict(values=header,
                    fill_color='firebrick',
                    align='center',
                    font=dict(color='white')),
        cells=dict(values=np.transpose(tablelist),
                   fill=dict(color=[colorlist, 'silver']),
                   height=22,
                   font_size=11,
                   align=['center', 'left', 'left', 'right', 'right']),
        )],layout=layout)

        nicetable.write_image(filename + '.jpeg', format="jpeg", scale=2, width=image_width, height=image_height)
        print(f"💾 Saved table as {filename}")


def save_cup_round_as_image(tablelist, header, tablename, foldername, is_results=False):
    image_height = 47 + 22 * len(tablelist)
    image_width = 720
    
    if not tablelist:
        raise ValueError("Table list is empty — cannot generate PNG.")

    layout = go.Layout(margin=dict(l=0, r=0, b=0, t=0))

    if not is_results:
        colorlist = ['silver']
        columnwid = [15, 35, 15, 4, 15, 35, 15]
        image_width = image_width
    else:
        columnwid = [20, 35, 15, 4, 15, 35, 20]
        image_width = image_width
        image_height = image_height - 20
        colorlist = []
        for row in tablelist:
            if row[2] > row[4]:
                colorrow = ['PaleGreen']*3 + ['silver'] + ['LightSalmon']*3
            elif row[2] < row[4]:
                colorrow = ['LightSalmon']*3 + ['silver'] + ['PaleGreen']*3
            else:
                colorrow = ['silver']*7
            colorlist.append(colorrow)
        # Transpose color matrix
        colorlist = list(map(list, zip(*colorlist)))

    # Table rendering
    fig = go.Figure(
        data=[go.Table(
            columnwidth=columnwid,
            header=dict(
                values=header,
                fill_color='firebrick',
                font=dict(color='white'),
                align='center'
            ),
            cells=dict(
                values=np.transpose(tablelist),
                fill=dict(color=colorlist),
                height=22,
                font_size=11,
                align=['left', 'center', 'right', 'center', 'left', 'center', 'left']
            )
        )],
        layout=layout
    )

    fig.write_image(f"{foldername}{tablename}.jpeg", width=image_width, height=image_height)
    print(f"💾 Saved table as {foldername}{tablename}")
