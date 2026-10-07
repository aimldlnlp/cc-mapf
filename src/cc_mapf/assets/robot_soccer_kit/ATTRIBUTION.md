# Robot Soccer Kit visual assets

Source: https://github.com/google-deepmind/mujoco_menagerie/tree/main/robot_soccer_kit

The MJCF and STL assets are distributed under the accompanying MIT LICENSE.
The upstream robot was converted from CAD with onshape-to-robot.

The visual assembly is scaled by 2.5 times the configured cell size and its
top marker is recolored per agent. Planar drive uses a conservative cylinder
envelope computed from transformed mesh vertices. Wheel drive retains native
wheel joints and passive roller collisions, scales their geometry, and uses
velocity actuators with explicit speed and torque limits. A chassis cylinder
provides the body collision envelope; mesh detail is not used for contacts.
Presentation styling changes lighting, colors and camera motion only.
