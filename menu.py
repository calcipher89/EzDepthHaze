import nuke

toolbar = nuke.menu("Nodes")
menu = toolbar.addMenu("EzDepthHaze")
menu.addCommand("EzDepthHaze", "nuke.createNode('EzDepthHaze')")
