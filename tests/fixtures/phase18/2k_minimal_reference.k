*KEYWORD
$ Compact fixed-width Phase 18 reference deck
*NODE
       1       0.0000000       0.0000000       0.0000000
       2       1.0000000       0.0000000       0.0000000
       3       1.0000000       1.0000000       0.0000000
       4       0.0000000       1.0000000       0.0000000
       5       0.0000000       0.0000000       1.0000000
       6       1.0000000       0.0000000       1.0000000
       7       1.0000000       1.0000000       1.0000000
       8       0.0000000       1.0000000       1.0000000
       9       2.0000000       0.0000000       0.0000000
      10       3.0000000       0.0000000       0.0000000
      11       2.0000000       1.0000000       0.0000000
      12       0.0000000       0.0000000       2.0000000
      13       0.0000000       0.0000000       2.0000000
      99       9.0000000       9.0000000       9.0000000
*ELEMENT_SOLID
     100     201
       1       2       3       4       5       6       7       8       0       0
*ELEMENT_BEAM
     200     202       9      10      12
     201     202      10      11      13
*PART
Concrete solid
       201         4         5         0         0         0         0         0
*PART
Rebar beam
       202         3        14         0         0         0         0         0
*SECTION_SOLID_TITLE
Concrete section
         4         1
*SECTION_BEAM_TITLE
Rebar section
         3         1
*MAT_CONCRETE_DAMAGE_REL3_TITLE
Concrete material
         52.40000E-9         0         0         0         0         0         0         0         0
         0         0         0         0         0         0         0         0         0         0
         0         0         0         0         0         1         0         0         0         0
*MAT_ADD_EROSION
         5         0         0         0
*DEFINE_CURVE
         1         0         1         1         0         0         0         0
       0       0
       1       1
*MAT_PLASTIC_KINEMATIC_TITLE
Rebar material
        147.85000E-9         0         0         0         0         0         0         0         0
*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE
Rebar embedded in concrete
       202       201         1         1         0         0         0         0
*SET_NODE_LIST_TITLE
Concrete nodes
       501
         1         2         3         4         5         6         7         8
         9        10        11
*SET_PART_LIST_TITLE
Embedded parts
       601
       201       202
*SET_SEGMENT_TITLE
Interface segments
       701
         1         2         3         4
         5         6         7         8
*END
